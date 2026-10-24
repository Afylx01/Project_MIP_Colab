import sys, json, math, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats as st

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (FILTER_RETRACE, FILTER_TREND, FILTER_RS,
                              FILTER_REGIME, FILTER_SECTOR_CAP,
                              LOOKBACK_VALUES, EMA_SPAN_VALUES)
from nextgen.risk_statistics import (compute_probabilistic_sharpe_ratio,
                                     compute_deflated_sharpe_ratio)
from core.universe_policy import MIN_ELIGIBLE_SYMBOLS

OUT = ROOT / "reports" / "analysis_evidence"
RF = 0.065

CANDIDATES = {
    "A_balanced": dict(lookback=315, ema=250, top_n=20, buffer=30, cap=2, sizing="equal_weight", regime=True),
    "B_max_sharpe": dict(lookback=315, ema=150, top_n=25, buffer=30, cap=3, sizing="equal_weight", regime=True),
    "C_max_cagr": dict(lookback=315, ema=150, top_n=20, buffer=20, cap=99, sizing="equal_weight", regime=True),
    "D_canonical": dict(lookback=252, ema=200, top_n=20, buffer=40, cap=2, sizing="atr_risk_parity", regime=True),
    "E_max_robust": dict(lookback=252, ema=200, top_n=30, buffer=20, cap=99, sizing="equal_weight", regime=True),
}

t0 = time.time()
runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
print("cube built", round(time.time() - t0, 1), "s")

def flags_for(c):
    f = FILTER_RETRACE | FILTER_TREND | FILTER_RS
    if c["regime"]:
        f |= FILTER_REGIME
    if c["cap"] < 90:
        f |= FILTER_SECTOR_CAP
    return f

def base_param(c, start_idx, end_idx, friction=15.0, slippage=5.0):
    return {
        "param_id": 0, "schedule_idx": 1,
        "start_date_idx": start_idx, "end_date_idx": end_idx,
        "lookback_idx": LOOKBACK_VALUES.index(c["lookback"]),
        "ema_idx": EMA_SPAN_VALUES.index(c["ema"]),
        "top_n": c["top_n"], "exit_buffer_rank": c["buffer"],
        "max_per_sector": c["cap"],
        "sizing_mode": c["sizing"],
        "filter_flags": flags_for(c),
        "retrace_threshold": 0.8, "initial_capital": 1_000_000.0,
        "friction_bps": friction, "slippage_bps": slippage,
        "risk_per_trade_pct": 1.0,
    }

def idx_for(start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e

def window_eligible(start):
    """PIT NIFTY500 members with the 252-bar history the strategy needs."""
    from core.pit_membership import coverage_stats
    return int(coverage_stats("NIFTY500", start, base_dir=ROOT)["eligible_symbols"])

def rebalance_indices(start, end):
    s, e = idx_for(start, end)
    off = int(cube.schedule_offsets[1]); ln = int(cube.schedule_lengths[1])
    idx = [int(i) for i in cube.rebalance_indices[off:off+ln] if s <= i <= e]
    return s, e, idx

def exact_curve(c, start, end, friction=15.0, slippage=5.0):
    s, e, idx = rebalance_indices(start, end)
    p = base_param(c, s, e, friction, slippage)
    dates, eq = [], []
    for i in idx:
        # The kernel executes and marks period NAV at sig_date+1 (T+1). Ending a
        # monthly run at the signal date would skip index-removal exits.
        j = min(i + 1, e)
        q = dict(p); q["end_date_idx"] = j
        arr = runner.engine.execute_sweep([q], cube, num_threads=1)
        v = float(arr[0]["ending_equity"])
        dates.append(cube.dates[j]); eq.append(v)
    return dates, np.array(eq, dtype=float)

def metrics_from_equity(eq, dates, start, end):
    # Include the last rebalance before the window so the first in-window month
    # is measured from its actual starting NAV.
    mask = np.array([(d >= start and d <= end) for d in dates])
    idx = np.where(mask)[0]
    if len(idx) < 2:
        return None
    if idx[0] > 0:
        idx = np.concatenate([[idx[0] - 1], idx])
    e = eq[idx]
    rets = np.diff(e) / e[:-1]
    n_months = len(rets)
    years = n_months / 12.0
    total = e[-1] / e[0] - 1.0
    cagr = (e[-1] / e[0]) ** (1.0 / max(years, 1e-9)) - 1.0
    vol = rets.std(ddof=1) * math.sqrt(12)
    sharpe = (rets.mean() * 12 - RF) / vol if vol > 0 else 0.0
    downside = rets[rets < RF / 12] - RF / 12
    dstd = downside.std(ddof=1) * math.sqrt(12) if len(downside) > 1 else vol
    sortino = (rets.mean() * 12 - RF) / dstd if dstd > 0 else 0.0
    peak = np.maximum.accumulate(e); dd = (e - peak) / peak
    mdd = dd.min()
    calmar = cagr / abs(mdd) if mdd < 0 else 0.0
    return {
        "months": int(n_months), "total_return_pct": round(total * 100, 2),
        "cagr_pct": round(cagr * 100, 2), "vol_pct": round(vol * 100, 2),
        "sharpe": round(sharpe, 2), "sortino": round(sortino, 2),
        "maxdd_pct": round(mdd * 100, 2), "calmar": round(calmar, 2),
        "win_rate_pct": round(float((rets > 0).mean() * 100), 1),
        "worst_month_pct": round(float(rets.min() * 100), 2),
        "best_month_pct": round(float(rets.max() * 100), 2),
        "_rets": rets, "_equity": e,
    }

def bench_curve(base_start, end="2026-08-31"):
    s, e, idx = rebalance_indices(base_start, end)
    # Match the strategy's T+1 period ends so both series cover the same months.
    js = [min(i + 1, e) for i in idx]
    return [cube.dates[j] for j in js], np.array([float(cube.bench_closes[j]) for j in js], dtype=float)

# Strategy and benchmark curves must share the same base rebalance so that
# metrics_from_equity applies the identical prepend rule to both. Otherwise a
# window compares e.g. 5 strategy months against 4 benchmark months.
BENCH_16 = bench_curve("2018-01-01")
BENCH_F = bench_curve("2018-01-01")

def bench_metrics(start, end):
    bd, be = BENCH_16
    return metrics_from_equity(be, bd, start, end)

WINDOWS = {
    "is_2018_2021": ("2018-01-01", "2021-12-31"),
    "oos_2022_2026": ("2022-01-01", "2026-08-31"),
    "full_2018_2026": ("2018-01-01", "2026-08-31"),
    "long_2008_2026": ("2008-01-01", "2026-08-31"),
    "gfc_2008": ("2008-01-01", "2008-12-31"),
    "euro_2011": ("2011-01-01", "2011-12-31"),
    "midcap_2018": ("2018-01-01", "2018-12-31"),
    "covid_2020": ("2020-01-01", "2020-05-29"),
}

results = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "universe": "NIFTY500", "benchmark": "NIFTY500",
           "candidates": {}, "benchmark": {}}

for name, c in CANDIDATES.items():
    print("==>", name)
    c_res = {"settings": c, "windows": {}, "alignment": {}}
    # Pre-2018 windows are refused by the PIT breadth gate. Only the 2018+ curve
    # is computed.
    dates_f, eq_f = None, None
    dates_16, eq_16 = exact_curve(c, "2018-01-01", "2026-08-31")
    for wname, (ws, we) in WINDOWS.items():
        elig = window_eligible(ws)
        if elig is not None and elig < MIN_ELIGIBLE_SYMBOLS:
            c_res["windows"][wname] = {
                "status": "REFUSED",
                "reason": "INSUFFICIENT_UNIVERSE_BREADTH",
                "eligible_symbols": elig,
                "min_eligible_symbols": MIN_ELIGIBLE_SYMBOLS,
            }
            c_res["alignment"][wname] = {"aligned": False, "refused": True, "eligible_symbols": elig}
            continue
        d, e, bd, be = dates_16, eq_16, BENCH_16[0], BENCH_16[1]
        m = metrics_from_equity(e, d, ws, we)
        bm = metrics_from_equity(be, bd, ws, we)
        if m is None:
            c_res["windows"][wname] = None; continue
        rets = m.pop("_rets"); m.pop("_equity")
        c_res["windows"][wname] = m
        if bm is not None:
            bm.pop("_rets"); bm.pop("_equity")
        c_res["alignment"][wname] = {
            "strategy_months": m["months"],
            "benchmark_months": None if bm is None else bm["months"],
            "strategy_first": dates_16[0],
            "aligned": bm is not None and m["months"] == bm["months"],
        }
    # cost sensitivity on full window
    d2, e2 = exact_curve(c, "2018-01-01", "2026-08-31", friction=30.0, slippage=10.0)
    cm = metrics_from_equity(e2, d2, "2018-01-01", "2026-08-31")
    cm.pop("_rets"); cm.pop("_equity")
    c_res["cost_30_10bps"] = cm
    # statistics on full monthly returns
    m = metrics_from_equity(eq_16, dates_16, "2018-01-01", "2026-08-31")
    r = m.pop("_rets"); m.pop("_equity")
    rb = bench_metrics("2018-01-01", "2026-08-31")
    br = rb.pop("_rets"); rb.pop("_equity")
    n = min(len(r), len(br)); r = r[:n]; br = br[:n]
    excess = r - RF / 12
    def safe(v):
        return None if v is None else round(float(v), 4)
    c_res["statistics"] = {
        "n_months": int(n),
        "psr_excess": safe(compute_probabilistic_sharpe_ratio(excess, benchmark_sr=0.0, annualization_factor=12)),
        "dsr_k5": safe(compute_deflated_sharpe_ratio(excess, n_trials=5, annualization_factor=12)),
        "dsr_k8000": safe(compute_deflated_sharpe_ratio(excess, n_trials=8000, annualization_factor=12)),
        "t_stat_vs_zero": round(float(st.ttest_1samp(r, 0.0, alternative="greater").statistic), 2),
        "p_value_vs_zero": round(float(st.ttest_1samp(r, 0.0, alternative="greater").pvalue), 6),
        "t_stat_vs_benchmark": round(float(st.ttest_rel(r, br, alternative="greater").statistic), 2),
        "p_value_vs_benchmark": round(float(st.ttest_rel(r, br, alternative="greater").pvalue), 6),
    }
    # alpha/beta
    beta, alpha_d, _, _, _ = st.linregress(br, r)
    c_res["statistics"]["beta_vs_nifty500"] = round(float(beta), 2)
    c_res["statistics"]["alpha_annual_pct"] = round(float(alpha_d * 12 * 100), 2)
    # bootstrap
    rng = np.random.default_rng(42)
    idx = rng.integers(0, n, size=(10000, n))
    sims = r[idx]
    cagrs = np.prod(1 + sims, axis=1) ** (12.0 / n) - 1
    shs = (sims.mean(axis=1) * 12 - RF) / (sims.std(axis=1, ddof=1) * math.sqrt(12))
    c_res["bootstrap"] = {
        "cagr_ci95": [round(float(np.percentile(cagrs, 2.5) * 100), 2), round(float(np.percentile(cagrs, 97.5) * 100), 2)],
        "sharpe_ci95": [round(float(np.percentile(shs, 2.5)), 2), round(float(np.percentile(shs, 97.5)), 2)],
        "prob_positive_cagr": round(float((cagrs > 0).mean()), 4),
    }
    c_res["full_2018_2026"] = m
    c_res["benchmark_full"] = rb
    results["candidates"][name] = c_res
    print("   full:", m, "| OOS:", c_res["windows"]["oos_2022_2026"])

# benchmark windows (same effective window as the strategy)
for wname, (ws, we) in WINDOWS.items():
    elig = window_eligible(ws)
    if elig is not None and elig < MIN_ELIGIBLE_SYMBOLS:
        results["benchmark"][wname] = {
            "status": "REFUSED",
            "reason": "INSUFFICIENT_UNIVERSE_BREADTH",
            "eligible_symbols": elig,
        }
        continue
    b = bench_metrics(ws, we)
    if b is None:
        results["benchmark"][wname] = None
        continue
    b.pop("_rets", None); b.pop("_equity", None)
    results["benchmark"][wname] = b

# yearly returns for the balanced candidate
def yearly_table(eq, dates, start, end):
    e = pd.Series(eq, index=pd.to_datetime(dates))
    e = e[(e.index >= pd.Timestamp(start)) & (e.index <= pd.Timestamp(end))]
    base = pd.Series([e.iloc[0]], index=[pd.Timestamp(start) - pd.Timedelta(days=1)])
    e2 = pd.concat([base, e])
    ye = e2.resample("YE").last()
    rets = ye.pct_change().dropna() * 100
    return {str(k.year): round(float(v), 2) for k, v in rets.items()}

d, e = exact_curve(CANDIDATES["A_balanced"], "2018-01-01", "2026-08-31")
results["balanced_yearly_returns_pct"] = yearly_table(e, d, "2018-01-01", "2026-08-31")

print(json.dumps({k: v for k, v in results.items() if k not in ("candidates", "benchmark")}, indent=2))
(OUT / "21_strategy_validation.json").write_text(json.dumps(results, indent=2, default=str))
print("saved", OUT / "validation_results.json")
