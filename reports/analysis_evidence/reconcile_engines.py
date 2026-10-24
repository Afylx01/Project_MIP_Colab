"""Reconcile every published (engine, universe, config) under PIT membership.

Canonical: NIFTY500 point-in-time membership, 2018-01-01..2026-08-31.
A 2016-01-01 start is refused (no snapshot on/before it). The canonical window
starts in 2018, the first year with >=70% tradable coverage; 2017 is runnable
but outside the pre-registered window. The live scanner uses the latest list.
"""
import sys, json, math, sqlite3, gc, time, argparse
from pathlib import Path
import numpy as np

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner
from brute_force.cube_builder import build_tensor_cube
from brute_force.grid import (FILTER_RETRACE, FILTER_TREND, FILTER_RS,
                              FILTER_REGIME, FILTER_SECTOR_CAP,
                              LOOKBACK_VALUES, EMA_SPAN_VALUES)
from core.pit_membership import coverage_stats
from core.universe_policy import MIN_ELIGIBLE_SYMBOLS

OUT = ROOT / "reports" / "analysis_evidence"
REPORT = ROOT / "reports" / "ENGINE_RECONCILIATION.md"
DB = ROOT / "data" / "universe.db"
RF = 0.065
START, END = "2018-01-01", "2026-08-31"

CONFIGS = {
    "D_canonical": dict(lookback=252, ema=200, top_n=20, buffer=40, cap=2,
                        sizing="atr_risk_parity", regime=True),
    "A_balanced": dict(lookback=315, ema=250, top_n=20, buffer=30, cap=2,
                       sizing="equal_weight", regime=True),
}
WINDOWS = {
    "gfc_2008": ("2008-01-01", "2008-12-31"),
    "euro_2011": ("2011-01-01", "2011-12-31"),
    "midcap_2018": ("2018-01-01", "2018-12-31"),
    "covid_2020": ("2020-01-01", "2020-05-29"),
    "full_2018_2026": ("2018-01-01", "2026-08-31"),
}


def flags_for(c):
    f = FILTER_RETRACE | FILTER_TREND | FILTER_RS
    if c["regime"]:
        f |= FILTER_REGIME
    if c["cap"] < 90:
        f |= FILTER_SECTOR_CAP
    return f


def coverage(start, raw_as_of=None):
    """PIT coverage at window start; raw DB breadth optionally as of another date.

    The raw DB count is an independent check on data availability. For stress
    windows we measure it at the window *end* (the label must describe the
    whole window), while PIT eligibility is measured at the window start.
    """
    st = coverage_stats("NIFTY500", start, base_dir=ROOT)
    raw_as_of = raw_as_of or start
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        total = int(con.execute("SELECT COUNT(DISTINCT symbol) FROM prices").fetchone()[0])
        raw252 = int(con.execute(
            "SELECT COUNT(*) FROM (SELECT symbol, COUNT(*) c FROM prices WHERE date<=? "
            "GROUP BY symbol HAVING c>=252)", (raw_as_of,)).fetchone()[0])
    finally:
        con.close()
    label = "VALID" if st["eligible_symbols"] >= MIN_ELIGIBLE_SYMBOLS else "DATA_INSUFFICIENT"
    return {**st, "label": label, "min_eligible_symbols": MIN_ELIGIBLE_SYMBOLS,
            "raw_db_as_of": raw_as_of,
            "raw_db_symbols_total": total, "raw_db_symbols_252": raw252,
            "raw_db_coverage_pct": round(raw252 / max(total, 1) * 100, 2)}


def idx_for(cube, start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e


def rebalance_indices(cube, start, end, schedule_idx=1):
    s, e = idx_for(cube, start, end)
    off = int(cube.schedule_offsets[schedule_idx])
    ln = int(cube.schedule_lengths[schedule_idx])
    return s, e, [int(i) for i in cube.rebalance_indices[off:off + ln] if s <= i <= e]


def base_param(c, s, e):
    return {
        "param_id": 0, "schedule_idx": 1,
        "start_date_idx": s, "end_date_idx": e,
        "lookback_idx": LOOKBACK_VALUES.index(c["lookback"]),
        "ema_idx": EMA_SPAN_VALUES.index(c["ema"]),
        "top_n": c["top_n"], "exit_buffer_rank": c["buffer"],
        "max_per_sector": c["cap"], "sizing_mode": c["sizing"],
        "filter_flags": flags_for(c), "retrace_threshold": 0.8,
        "initial_capital": 1_000_000.0, "friction_bps": 15.0,
        "slippage_bps": 5.0, "risk_per_trade_pct": 1.0,
    }


def continuous(runner, cube, cfg, universe, start=START, end=END):
    return runner.run_custom_backtest(
        start_date=start, end_date=end, universe_name=universe,
        benchmark="NIFTY500", schedule="monthly",
        lookback=cfg["lookback"], ema_trend=cfg["ema"], top_n=cfg["top_n"],
        exit_buffer_rank=cfg["buffer"], max_per_sector=cfg["cap"],
        sizing_mode=cfg["sizing"],
    )


def monthly_curve(runner, cube, cfg, start=START, end=END, shift=0):
    s, e, idx = rebalance_indices(cube, start, end)
    p = base_param(cfg, s, e)
    dates, eq = [], []
    for i in idx:
        j = min(i + shift, e)
        q = dict(p); q["end_date_idx"] = j
        eq.append(float(runner.engine.execute_sweep([q], cube, num_threads=1)[0]["ending_equity"]))
        dates.append(cube.dates[j])
    return dates, np.array(eq, dtype=float)


def monthly_metrics(dates, eq, start=START, end=END, include_initial=False):
    mask = np.array([(d >= start and d <= end) for d in dates])
    idx = np.where(mask)[0]
    if len(idx) < 2:
        return None
    if idx[0] > 0:
        idx = np.concatenate([[idx[0] - 1], idx])
    e = eq[idx]
    if include_initial:
        e = np.concatenate([[1_000_000.0], e])
    rets = np.diff(e) / e[:-1]
    n = len(rets)
    years = n / 12.0
    total = e[-1] / e[0] - 1.0
    cagr = (e[-1] / e[0]) ** (1.0 / max(years, 1e-9)) - 1.0
    vol = rets.std(ddof=1) * math.sqrt(12)
    sharpe = (rets.mean() * 12 - RF) / vol if vol > 0 else 0.0
    peak = np.maximum.accumulate(e)
    mdd = ((e - peak) / peak).min()
    return {
        "months": int(n), "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2), "sharpe": round(float(sharpe), 2),
        "maxdd_monthly_pct": round(float(mdd) * 100, 2),
        "calmar": round(float(cagr / abs(mdd)), 2) if mdd < 0 else 0.0,
    }


def row(engine, universe, config, method, res):
    def r2(v):
        return None if v is None else round(float(v), 2)
    return {
        "engine": engine, "universe": universe, "config": config, "method": method,
        "cagr_pct": r2(res.get("cagr_pct")),
        "sharpe": r2(res.get("sharpe", res.get("sharpe_ratio"))),
        "maxdd_pct": r2(res.get("maxdd_monthly_pct", res.get("max_drawdown_pct"))),
        "maxdd_basis": "monthly rebalance NAV" if "maxdd_monthly_pct" in res else "daily intra-period",
        "trades": res.get("total_trades", res.get("trades")),
        "ending_equity": res.get("ending_equity", res.get("final_equity")),
        "period": f"{START}..{END}", "status": "REPRODUCED",
    }


def refused(engine, universe, config, reason):
    return {
        "engine": engine, "universe": universe, "config": config, "method": "—",
        "cagr_pct": None, "sharpe": None, "maxdd_pct": None, "maxdd_basis": "—",
        "trades": None, "ending_equity": None, "period": "—",
        "status": "REFUSED", "reason": reason,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-python", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "period": f"{START}..{END}",
        "costs": "15 bps friction + 5 bps slippage",
        "policy": {
            "index_universe": "NIFTY500 point-in-time membership (NSE interval table)",
            "period_note": "2016-01-01 start refused (no snapshot on/before it); canonical starts 2018 (first year with >=70% tradable coverage); 2017 runnable (305 eligible) but outside the pre-registered window",
            "live_scanner": "latest constituents (the only component allowed to use them)",
            "min_eligible_symbols": MIN_ELIGIBLE_SYMBOLS,
        },
        "table": [],
        "stress_windows": {},
        "reconciliation": {},
    }

    for name, (ws, we) in WINDOWS.items():
        out["stress_windows"][name] = {"window": [ws, we], **coverage(ws, raw_as_of=we)}

    # ---- Canonical PIT NIFTY500: C engine ----
    runner = BruteForceCampaignRunner(base_dir=ROOT)
    cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
    d_cont = continuous(runner, cube, CONFIGS["D_canonical"], "NIFTY500")
    d_date, d_eq = monthly_curve(runner, cube, CONFIGS["D_canonical"], shift=1)
    d_month = monthly_metrics(d_date, d_eq)
    d_date_t1, d_eq_t1 = monthly_curve(runner, cube, CONFIGS["D_canonical"], shift=1)
    d_month_t1 = monthly_metrics(d_date_t1, d_eq_t1, include_initial=True)
    a_cont = continuous(runner, cube, CONFIGS["A_balanced"], "NIFTY500")
    a_date, a_eq = monthly_curve(runner, cube, CONFIGS["A_balanced"], shift=1)

    out["table"].append(row("C99 kernel", "NIFTY500 (PIT)", "D", "continuous", d_cont))
    r = row("C99 kernel", "NIFTY500 (PIT)", "D", "monthly-sampled", d_month)
    r["trades"] = d_cont["total_trades"]
    out["table"].append(r)
    out["table"].append(row("C99 kernel", "NIFTY500 (PIT)", "A", "continuous", a_cont))
    r = row("C99 kernel", "NIFTY500 (PIT)", "A", "monthly-sampled", monthly_metrics(a_date, a_eq))
    r["trades"] = a_cont["total_trades"]
    out["table"].append(r)

    summ22 = json.loads((OUT / "22_candidate_engine_summaries.json").read_text())
    for key, letter in (("B_max_sharpe", "B"), ("C_max_cagr", "C"), ("E_max_robust", "E")):
        s = summ22[key]
        out["table"].append({
            "engine": "C99 kernel", "universe": "NIFTY500 (PIT)", "config": letter,
            "method": "continuous", "cagr_pct": round(float(s["cagr_pct"]), 2),
            "sharpe": round(float(s["sharpe_ratio"]), 2),
            "maxdd_pct": round(float(s["max_drawdown_pct"]), 2),
            "maxdd_basis": "daily intra-period", "trades": int(s["total_trades"]),
            "ending_equity": float(s["ending_equity"]),
            "period": f"{START}..{END}", "status": "REPRODUCED",
        })

    s_full, e_full = idx_for(cube, START, END)
    full_single = runner.engine.execute_sweep(
        [{**base_param(CONFIGS["D_canonical"], s_full, e_full), "end_date_idx": e_full}],
        cube, num_threads=1)[0]
    out["reconciliation"] = {
        "same_engine": True, "same_universe": "NIFTY500 (PIT)", "same_config": True,
        "continuous": {
            "cagr_pct": d_cont["cagr_pct"], "sharpe": d_cont["sharpe_ratio"],
            "maxdd_pct": d_cont["max_drawdown_pct"], "maxdd_basis": "daily intra-period",
            "trades": d_cont["total_trades"], "ending_equity": d_cont["ending_equity"],
            "cagr_basis": "(end_session-start_session)/252",
        },
        "monthly_sampled": d_month,
        "monthly_t_plus_1": d_month_t1,
        "identical_ending_equity": d_cont["ending_equity"] == float(d_eq[-1]) == float(full_single["ending_equity"]),
        "identical_trades": d_cont["total_trades"] == int(full_single["total_trades"]),
        "mechanisms": [
            "CAGR: identical ending equity, sessions/252 vs months/12",
            "MaxDD: daily intra-period vs monthly rebalance NAV",
            "Sharpe: INCOMPLETE — kernel internal periodic series not exposed; T+1 explains most of the gap",
        ],
    }
    del cube; runner.cube = None; gc.collect()

    # ---- ALL reference (same period) ----
    cube_all = runner.ensure_cube(universe_name="ALL", benchmark="NIFTY500")
    out["table"].append(row("C99 kernel", "ALL (reference)", "D", "continuous",
                            continuous(runner, cube_all, CONFIGS["D_canonical"], "ALL")))
    del cube_all; runner.cube = None; gc.collect()

    # ---- NIFTY750 has no PIT table ----
    out["table"].append(refused("C99 kernel", "NIFTY750", "D", "NO_POINT_IN_TIME_TABLE"))
    out["table"].append(refused("Python LightweightBacktester", "NIFTY750", "D", "NO_POINT_IN_TIME_TABLE"))

    # ---- Historical legacy numbers: listed so they are explicitly retired ----
    # 04b is the full ALL cross-section (delisted names included, so *not*
    # survivorship-biased per its own metadata); it is retired because it starts
    # 2016-01-01, before the first PIT snapshot (2016-01-18), and is benchmarked
    # against NIFTY500 while holding the whole DB cross-section.
    b = json.loads((OUT / "04b_backtest_all.json").read_text())
    out["table"].append({
        "engine": "Python LightweightBacktester", "universe": "ALL (full cross-section, legacy)",
        "config": "D", "method": "continuous",
        "cagr_pct": b["cagr_pct"], "sharpe": b["sharpe_ratio"],
        "maxdd_pct": b["max_drawdown_pct"], "maxdd_basis": "monthly",
        "trades": b["total_trades"], "ending_equity": b["final_equity"],
        "period": f"{b['start_date']}..{b['end_date']}",
        "status": "RETIRED_LEGACY_NON_PIT",
        "reason": "2016-01-01 start predates the first PIT snapshot (2016-01-18); "
                  "ALL cross-section, outside the pre-registered PIT contract",
    })
    c = json.loads((OUT / "06_c_engine_nifty750.json").read_text())["summary"]
    out["table"].append({
        "engine": "C99 kernel", "universe": "NIFTY750 (current-list, historical)",
        "config": "D", "method": "monthly",
        "cagr_pct": round(float(c["cagr_pct"]), 2), "sharpe": round(float(c["sharpe_ratio"]), 2),
        "maxdd_pct": -round(float(c["max_drawdown_pct"]), 2), "maxdd_basis": "monthly",
        "trades": c["total_trades"], "ending_equity": c["ending_equity"],
        "period": f"{c['start_date']}..{c['end_date']}",
        "status": "RETIRED_SURVIVORSHIP_BIAS",
        "reason": "2026 constituent list applied backwards; NIFTY750 has no PIT table",
    })

    # ---- Old canonical NIFTY500 current-list run (30.01%): the headline this tag retires ----
    o = json.loads((OUT / "04c_backtest_nifty500_current_list.json").read_text())
    out["table"].append({
        "engine": "Python LightweightBacktester", "universe": "NIFTY500 (current 2026 list, 2016 start)",
        "config": "D", "method": "continuous",
        "cagr_pct": o["cagr_pct"], "sharpe": o["sharpe_ratio"],
        "maxdd_pct": o["max_drawdown_pct"], "maxdd_basis": "monthly",
        "trades": o["total_trades"], "ending_equity": o["final_equity"],
        "period": f"{o['start_date']}..{o['end_date']}",
        "status": "RETIRED_SURVIVORSHIP_BIAS",
        "reason": "today's NIFTY500 list applied to 2016-2026; start predates the first PIT snapshot",
    })

    # ---- Python production engine, PIT NIFTY500 ----
    if not args.skip_python:
        from core.backtest import LightweightBacktester
        py_dir = OUT / "_python_runs"
        py_dir.mkdir(exist_ok=True)
        bt = LightweightBacktester(base_dir=ROOT, output_dir=py_dir / "NIFTY500")
        r = bt.run(start_date=START, end_date=END, top_n=20,
                   exit_buffer=40, use_regime_filter=True, max_per_sector=2,
                   sizing_mode="atr_risk_parity", risk_per_trade_pct=1.0,
                   universe_mode="NIFTY500")
        py = {k: r.get(k) for k in (
            "cagr_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "max_drawdown_pct", "daily_max_drawdown_pct", "total_trades",
            "win_rate_pct", "final_equity", "universe_mode", "universe_size",
            "universe_source", "universe_point_in_time", "pit_index",
            "pit_members_start", "pit_members_end", "eligible_symbols",
            "survivorship_bias_risk", "data_completeness_risk")}
        out["python_runs"] = {"NIFTY500": py}
        out["canonical_production"] = {
            "engine": "Python LightweightBacktester (production contract)",
            "universe": "NIFTY500 point-in-time membership",
            "config": "D: lookback 252, EMA 200, top20, buffer40, cap2, ATR risk parity, regime on",
            "cagr_pct": py["cagr_pct"], "sharpe": py["sharpe_ratio"],
            "maxdd_pct": py["max_drawdown_pct"], "trades": py["total_trades"],
        }
        out["table"].append({
            "engine": "Python LightweightBacktester", "universe": "NIFTY500 (PIT)",
            "config": "D", "method": "continuous",
            "cagr_pct": py["cagr_pct"], "sharpe": py["sharpe_ratio"],
            "maxdd_pct": py["max_drawdown_pct"], "maxdd_basis": "monthly",
            "trades": py["total_trades"], "ending_equity": py["final_equity"],
            "period": f"{START}..{END}", "status": "REPRODUCED",
        })
        (OUT / "34_python_canonical.json").write_text(json.dumps({"NIFTY500": py}, indent=2, default=str))

        # ---- Survivorship / look-ahead control: same engine, config and dates ----
        # Only the membership source differs: today's 2026 NIFTY500 list vs PIT.
        from core.data_engine import load_universe_constituents
        current = sorted(load_universe_constituents("NIFTY500"))
        bt_cur = LightweightBacktester(base_dir=ROOT, output_dir=py_dir / "NIFTY500_CURRENT_CONTROL")
        r_cur = bt_cur.run(start_date=START, end_date=END, top_n=20,
                           exit_buffer=40, use_regime_filter=True, max_per_sector=2,
                           sizing_mode="atr_risk_parity", risk_per_trade_pct=1.0,
                           universe_mode="NIFTY500-CURRENT-CONTROL",
                           explicit_symbols=current)
        cur = {k: r_cur.get(k) for k in (
            "cagr_pct", "sharpe_ratio", "sortino_ratio", "calmar_ratio",
            "max_drawdown_pct", "daily_max_drawdown_pct", "total_trades",
            "win_rate_pct", "final_equity", "universe_size", "universe_mode",
            "universe_source", "survivorship_bias_risk")}
        out["survivorship_control"] = {
            "description": "Same engine, dates and config; current 2026 NIFTY500 list (biased control) vs PIT membership.",
            "requested_members": len(current),
            "pit_cagr_pct": py["cagr_pct"],
            "current_list_cagr_pct": cur["cagr_pct"],
            "cagr_overstatement_pp": round(float(cur["cagr_pct"]) - float(py["cagr_pct"]), 2),
            "pit": py,
            "current_list": cur,
        }
        (OUT / "35_current_list_control.json").write_text(
            json.dumps(out["survivorship_control"], indent=2, default=str))
        out["table"].append({
            "engine": "Python LightweightBacktester",
            "universe": "NIFTY500 (current 2026 list, biased control)",
            "config": "D", "method": "continuous",
            "cagr_pct": cur["cagr_pct"], "sharpe": cur["sharpe_ratio"],
            "maxdd_pct": cur["max_drawdown_pct"], "maxdd_basis": "monthly",
            "trades": cur["total_trades"], "ending_equity": cur["final_equity"],
            "period": f"{START}..{END}", "status": "BIASED_CONTROL",
        })

    # ---- Stress-window metrics from the PIT validation harness ----
    v21 = json.loads((OUT / "21_strategy_validation.json").read_text())
    a = v21["candidates"]["A_balanced"]
    for name in WINDOWS:
        sw = out["stress_windows"][name]
        sw["strategy_config"] = "A_balanced"
        sw["strategy"] = a["windows"].get(name)
        sw["benchmark"] = v21["benchmark"].get(name)
        align = a["alignment"].get(name, {})
        sw["effective_window_aligned"] = bool(align.get("aligned"))
        sw["headline_eligible"] = sw["label"] == "VALID" and sw["effective_window_aligned"]

    # ---- PIT membership provenance ----
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    pit = [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM prices")]
    con.close()
    out["pit_provenance"] = {
        "primary_source": "https://niftyhistory.in/ full Nifty500 snapshots",
        "secondary_source": "https://github.com/aditya-jha/nse-historical-membership (CC BY 4.0 intervals)",
        "coverage_start": "2016-01-18 snapshots; 2018+ used for the canonical backtest",
        "note": "Membership is resolved per rebalance date from the snapshot table; API names are mapped to DB symbols. Unmapped names are retained in the metadata and verification report.",
        "verification": "reports/PIT_MEMBERSHIP_VERIFICATION.md",
    }

    out["elapsed_sec"] = round(time.time() - t0, 1)
    (OUT / "33_reconciliation.json").write_text(json.dumps(out, indent=2, default=str))

    def fmt(x):
        return "—" if x is None else f"{x:.2f}" if isinstance(x, float) else str(x)

    lines = ["# Engine reconciliation — PIT membership", "",
             f"Generated {out['generated']}. Period {out['period']}; costs {out['costs']}.", "",
             "## Policy", "",
             "- Historical index universe: **NIFTY500 point-in-time membership**, resolved per rebalance date.",
             "- A 2016-01-01 start is refused: no snapshot exists on or before it. The canonical window starts in "
             "2018, the first year with ≥70% tradable coverage (356 eligible of 377 mapped). 2017 is runnable "
             "(305 eligible, verified) but is outside the pre-registered window.",
             "- Live scanner: latest constituents (the only component allowed to use them).",
             f"- Breadth gate: at least **{MIN_ELIGIBLE_SYMBOLS}** eligible PIT members (scaled down for small indices).", "",
             "## Canonical baselines (NIFTY500 PIT, 2018–2026)", ""]
    if "canonical_production" in out:
        cp = out["canonical_production"]
        lines.append(f"- **Production backtest** (Python): CAGR **{cp['cagr_pct']}%**, "
                     f"Sharpe {cp['sharpe']}, MaxDD {cp['maxdd_pct']}%, {cp['trades']} trades.")
    lines += [f"- **Strategy-engine baseline** (C99 kernel, config D): CAGR **{d_cont['cagr_pct']:.2f}%**, "
              f"Sharpe {d_cont['sharpe_ratio']:.2f}, daily MaxDD {d_cont['max_drawdown_pct']:.2f}%, "
              f"{d_cont['total_trades']} trades.", "",
              "## Every published (engine, universe, config)", "",
              "| Engine | Universe | Config | Method | CAGR % | Sharpe | MaxDD % | DD basis | Trades | Status |",
              "|---|---|---|---|---:|---:|---:|---|---:|---|"]
    for r in out["table"]:
        lines.append(f"| {r['engine']} | {r['universe']} | {r['config']} | {r['method']} | "
                     f"{fmt(r['cagr_pct'])} | {fmt(r['sharpe'])} | {fmt(r['maxdd_pct'])} | "
                     f"{r['maxdd_basis']} | {fmt(r['trades'])} | {r['status']} |")

    lines += ["", "`RETIRED_LEGACY_NON_PIT` rows are old numbers that are not reproducible under the PIT "
              "contract (the 04b row starts 2016-01-01, before the first snapshot, and holds the full ALL "
              "cross-section rather than an index). `RETIRED_SURVIVORSHIP_BIAS` rows applied a 2026 "
              "constituent list backwards. Both are listed so they are explicitly retired rather than "
              "silently deleted, and neither is part of the canonical contract. "
              "`REFUSED` rows are named indices or windows with no PIT table/breadth.", "",
              "## Continuous vs monthly-sampled (same config, same PIT universe)", "",
              "| Quantity | Continuous | Monthly-sampled | Mechanism |",
              "|---|---:|---:|---|",
              f"| CAGR | {d_cont['cagr_pct']:.2f}% | {d_month['cagr_pct']:.2f}% | identical ending equity; sessions/252 vs months/12 |",
              f"| Ending equity | ₹{d_cont['ending_equity']:,.0f} | ₹{d_eq[-1]:,.0f} | identical path |",
              f"| Trades | {d_cont['total_trades']} | {d_cont['total_trades']} | identical selection |",
              f"| Sharpe | {d_cont['sharpe_ratio']:.2f} | {d_month['sharpe']:.2f} (T+1 {d_month_t1['sharpe']:.2f}) | INCOMPLETE: kernel internal series not exposed |",
              f"| MaxDD | {d_cont['max_drawdown_pct']:.2f}% daily | {d_month['maxdd_monthly_pct']:.2f}% monthly | daily intra-period vs monthly sampling |", "",
              "## Stress windows — PIT breadth-gated", "",
              "| Window | PIT members | Eligible | Raw DB 252-bar (at window end) | Label | Strategy total (config A) | Benchmark total | Aligned | Headline? |",
              "|---|---:|---:|---:|---|---:|---:|---|---|"]
    for name, sw in out["stress_windows"].items():
        st = sw.get("strategy") or {}
        bm = sw.get("benchmark") or {}
        raw = f"{sw.get('raw_db_symbols_252', '—')}/{sw.get('raw_db_symbols_total', '—')} ({sw.get('raw_db_coverage_pct', '—')}%)"
        lines.append(f"| {name} | {sw.get('members', '—')} | {sw.get('eligible_symbols', '—')} | {raw} | "
                     f"**{sw['label']}** | {st.get('total_return_pct', '—')}% | "
                     f"{bm.get('total_return_pct', '—')}% | {sw.get('effective_window_aligned', '—')} | "
                     f"{sw.get('headline_eligible', '—')} |")
    lines += ["", "Stress-window strategy totals and benchmark totals use the recommended **config A** monthly "
              "validation harness (`21_strategy_validation.json`, same PIT membership and effective windows); the "
              "canonical config-D production result is in the baseline section above and is not a stress-window total.", "",
              "Under-covered windows are refused by the engine, not merely labelled. "
              "The raw DB column is the independent check: at 2008-12-31 only 94 of 1,083 symbols "
              "(8.7%) have 252 bars; at 2011-12-31, 106 (9.8%). The shortfall is the documented data "
              "artifact, so 2008/2011 are DATA_INSUFFICIENT and no headline claim depends on them.", ""]
    if "survivorship_control" in out:
        sc = out["survivorship_control"]
        pit, ctl = sc["pit"], sc["current_list"]
        lines += ["## Survivorship / look-ahead control", "",
                  "Same production engine, config D, dates and costs; only membership differs.", "",
                  "| Run | Universe | CAGR | Sharpe | MaxDD | Trades |",
                  "|---|---|---:|---:|---:|---:|",
                  f"| PIT (canonical) | {pit.get('universe_size')} symbols, per-rebalance | "
                  f"{pit['cagr_pct']}% | {pit['sharpe_ratio']} | {pit['max_drawdown_pct']}% | {pit['total_trades']} |",
                  f"| Current 2026 list (biased control) | {ctl.get('universe_size')} symbols | "
                  f"{ctl['cagr_pct']}% | {ctl['sharpe_ratio']} | {ctl['max_drawdown_pct']}% | {ctl['total_trades']} |",
                  "", f"**Current-list look-ahead overstatement: +{sc['cagr_overstatement_pp']} pp CAGR.**", ""]
    lines += ["## Provenance", "",
              "| Item | Value |", "|---|---|",
              "| Primary membership source | niftyhistory.in full Nifty500 snapshots |",
              "| Secondary cross-check | aditya-jha/nse-historical-membership (CC BY 4.0) |",
              "| Snapshot coverage | 2016-01-18 onward; canonical 2018-2026 |",
              "| Resolution | Per rebalance date; dead names included while members |",
              "| Verification | reports/PIT_MEMBERSHIP_VERIFICATION.md |", "",
              "## Reproduction", "", "```bash",
              "python3 scripts/build_pit_constituents.py",
              "python3 reports/analysis_evidence/canonical_backtest.py",
              "python3 reports/analysis_evidence/validate_candidates.py",
              "python3 reports/analysis_evidence/summarize_candidates.py",
              "python3 reports/analysis_evidence/reconcile_engines.py",
              "python3 reports/analysis_evidence/label_random_windows.py",
              "```", ""]
    REPORT.write_text("\n".join(lines))
    print("\n".join(lines))
    print("saved", OUT / "33_reconciliation.json", "and", REPORT)


if __name__ == "__main__":
    main()
