import sys, json, time, gc, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner
from brute_force.cube_builder import build_tensor_cube
from brute_force.grid import (CANONICAL_BASELINE, FILTER_RETRACE, FILTER_TREND,
                              FILTER_RS, FILTER_REGIME, FILTER_SECTOR_CAP,
                              FILTER_VOL_TARGETING, LOOKBACK_VALUES,
                              EMA_SPAN_VALUES, SCHEDULE_MAP)
from core.universe_policy import MIN_ELIGIBLE_SYMBOLS, check_breadth

OUT = ROOT / "reports" / "analysis_evidence"
RF = 0.065
W = dict(lookback=315, ema=250, top_n=20, buffer=30, cap=2, sizing="equal_weight", regime=True)
RNG = np.random.default_rng(20261023)


class NpEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, np.integer):
            return int(o)
        if isinstance(o, np.floating):
            return float(o)
        if isinstance(o, np.bool_):
            return bool(o)
        return super().default(o)

def flags(c, vol_target=False):
    f = FILTER_RETRACE | FILTER_TREND | FILTER_RS
    if c.get("regime", True): f |= FILTER_REGIME
    if c.get("cap", 2) < 90: f |= FILTER_SECTOR_CAP
    if vol_target: f |= FILTER_VOL_TARGETING
    return f

def param(c, s, e, friction=15.0, slippage=5.0, vol_target=None):
    if vol_target is None: vol_target = c.get("vol_target", False)
    return {
        "param_id": 0, "schedule_idx": 1, "start_date_idx": s, "end_date_idx": e,
        "lookback_idx": LOOKBACK_VALUES.index(c["lookback"]),
        "ema_idx": EMA_SPAN_VALUES.index(c["ema"]),
        "top_n": c["top_n"], "exit_buffer_rank": c["buffer"],
        "max_per_sector": c["cap"],
        "sizing_mode": c["sizing"],
        "filter_flags": flags(c, vol_target),
        "retrace_threshold": 0.8, "initial_capital": 1_000_000.0,
        "friction_bps": friction, "slippage_bps": slippage,
        "risk_per_trade_pct": 1.0,
    }

def idx_for(cube, start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e

def eligible_at(s):
    """PIT members with 252 bars at the given session index."""
    mask = getattr(cube, "valid_price_mask", None)
    if mask is None:
        return None
    combined = np.asarray(mask[: int(s) + 1])
    membership = getattr(cube, "universe_membership_mask", None)
    if membership is not None:
        combined = combined & np.asarray(membership[: int(s) + 1])
    counts = combined.sum(axis=0)
    return int((counts >= 252).sum())

def bench_cagr(cube, start, end):
    s, e = idx_for(cube, start, end)
    b0, b1 = float(cube.bench_closes[s]), float(cube.bench_closes[e])
    years = (pd.Timestamp(cube.dates[e]) - pd.Timestamp(cube.dates[s])).days / 365.25
    return ((b1 / b0) ** (1 / max(years, 1e-9)) - 1) * 100 if b0 > 0 and b1 > 0 else 0.0

def dist(vals, label):
    v = np.asarray(vals, dtype=float)
    return {"n": int(len(v)), "median": round(float(np.median(v)), 2),
            "p05": round(float(np.percentile(v, 5)), 2),
            "p95": round(float(np.percentile(v, 95)), 2),
            "min": round(float(v.min()), 2), "max": round(float(v.max()), 2),
            "pct_positive": round(float((v > 0).mean() * 100), 1)}

t0 = time.time()
runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
print("cube", round(time.time() - t0, 1), "s")
results = {"generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "recommended": W, "tests": {}}

# ---------------- R1 random rolling windows ----------------
dates = [d for d in cube.dates if "2018-01-01" <= d <= "2026-08-31"]
start_candidates = [d for d in dates if d <= "2024-08-31"]
r1 = []
for _ in range(200):
    start = start_candidates[int(RNG.integers(0, len(start_candidates)))]
    months = int(RNG.integers(24, 61))
    end_ts = min(pd.Timestamp(start) + pd.DateOffset(months=months), pd.Timestamp("2026-08-31"))
    s, _e = idx_for(cube, start, "2026-08-31")
    e = idx_for(cube, start, str(end_ts.date()))[1]
    if e - s < 200:
        continue
    elig = eligible_at(s)
    label = "VALID" if (elig is not None and elig >= MIN_ELIGIBLE_SYMBOLS) else "DATA_INSUFFICIENT"
    base = {"start": cube.dates[s], "end": cube.dates[e], "months": int(e - s),
            "eligible_symbols": elig, "label": label}
    if label != "VALID":
        r1.append({**base, "cagr": np.nan, "sharpe": np.nan, "maxdd": np.nan,
                   "calmar": np.nan, "trades": 0, "bench_cagr": np.nan, "excess": np.nan})
        continue
    p = param(W, s, e)
    row = runner.engine.execute_sweep([p], cube, num_threads=1)[0]
    bc = bench_cagr(cube, cube.dates[s], cube.dates[e])
    r1.append({**base, "cagr": float(row["cagr"]), "sharpe": float(row["sharpe"]),
               "maxdd": float(row["max_drawdown"]), "calmar": float(row["calmar"]),
               "trades": int(row["total_trades"]), "bench_cagr": bc,
               "excess": float(row["cagr"]) - bc})
r1df = pd.DataFrame(r1)
valid = r1df[r1df.label == "VALID"]
insufficient = r1df[r1df.label == "DATA_INSUFFICIENT"]
results["tests"]["R1_random_windows"] = {
    "windows": len(r1df),
    "valid_windows": int(len(valid)),
    "data_insufficient_windows": int(len(insufficient)),
    "cagr": dist(valid.cagr, "cagr"),
    "sharpe": dist(valid.sharpe, "sharpe"),
    "maxdd": dist(valid.maxdd, "maxdd"),
    "excess": dist(valid.excess, "excess"),
    "pct_beat_benchmark": round(float((valid.excess > 0).mean() * 100), 1),
    # kernel max_drawdown is reported as a positive percentage
    "pct_dd_under_20": round(float((valid.maxdd < 20).mean() * 100), 1),
    "pct_dd_under_30": round(float((valid.maxdd < 30).mean() * 100), 1),
    "worst_window": valid.sort_values("cagr").iloc[0].to_dict(),
    "best_window": valid.sort_values("cagr").iloc[-1].to_dict(),
    "data_insufficient_median_cagr": round(float(insufficient.cagr.median()), 2) if len(insufficient) else None,
}
r1df.to_csv(OUT / "24_random_windows.csv", index=False)
print("R1 done", results["tests"]["R1_random_windows"]["cagr"], results["tests"]["R1_random_windows"]["pct_beat_benchmark"],
      "valid", len(valid), "insufficient", len(insufficient))

# ---------------- R2 random parameter perturbations ----------------
combos = list(itertools.product([189, 252, 315], [150, 200, 250], [15, 20, 25],
                               [20, 30, 40], [1, 2, 3], ["equal_weight", "atr_risk_parity"]))
RNG.shuffle(combos)
combos = combos[:500]
s_is, e_is = idx_for(cube, "2018-01-01", "2021-12-31")
s_oos, e_oos = idx_for(cube, "2022-01-01", "2026-08-31")
check_breadth(eligible_at(s_is), "FULL_CROSS_SECTION")
check_breadth(eligible_at(s_oos), "FULL_CROSS_SECTION")
params_is, params_oos = [], []
for i, (lb, ema, tn, buf, cap, sizing) in enumerate(combos):
    c = dict(lookback=lb, ema=ema, top_n=tn, buffer=buf, cap=cap, sizing=sizing, regime=True)
    p = param(c, s_is, e_is); p["param_id"] = i; params_is.append(p)
    q = param(c, s_oos, e_oos); q["param_id"] = i; params_oos.append(q)
dis = runner.engine.run_sweep(cube, params_is, num_threads=8)
dos = runner.engine.run_sweep(cube, params_oos, num_threads=8)
m = pd.DataFrame({"param_id": range(len(combos)),
                  "is_cagr": dis["cagr"], "is_sharpe": dis["sharpe"], "is_dd": dis["max_drawdown"],
                  "oos_cagr": dos["cagr"], "oos_sharpe": dos["sharpe"], "oos_dd": dos["max_drawdown"]})
for k, col in enumerate(("lookback", "ema", "top_n", "buffer", "cap", "sizing")):
    m[col] = [c[k] for c in combos]
results["tests"]["R2_random_perturbations"] = {
    "n": len(m),
    "is_cagr": dist(m.is_cagr, "is"), "is_sharpe": dist(m.is_sharpe, "is"),
    "oos_cagr": dist(m.oos_cagr, "oos"), "oos_sharpe": dist(m.oos_sharpe, "oos"),
    "oos_dd": dist(m.oos_dd, "dd"),
    "pct_oos_positive": round(float((m.oos_cagr > 0).mean() * 100), 1),
    "pct_oos_beat_bench": round(float((m.oos_cagr > bench_cagr(cube, "2022-01-01", "2026-08-31")).mean() * 100), 1),
    "corr_is_oos_cagr": round(float(m.is_cagr.corr(m.oos_cagr)), 3),
    "corr_is_oos_sharpe": round(float(m.is_sharpe.corr(m.oos_sharpe)), 3),
}
m.to_csv(OUT / "25_random_perturbations.csv", index=False)
print("R2 done", results["tests"]["R2_random_perturbations"]["pct_oos_beat_bench"])

# ---------------- R3 random cost regimes ----------------
s_f, e_f = idx_for(cube, "2018-01-01", "2026-08-31")
check_breadth(eligible_at(s_f), "FULL_CROSS_SECTION")
cost_params = []
costs = []
for i in range(200):
    fric = float(RNG.uniform(5, 50)); slip = float(RNG.uniform(0, 25))
    p = param(W, s_f, e_f, friction=fric, slippage=slip); p["param_id"] = i
    cost_params.append(p); costs.append((fric, slip))
arr = runner.engine.execute_sweep(cost_params, cube, num_threads=8)
cdf = pd.DataFrame({"friction_bps": [c[0] for c in costs], "slippage_bps": [c[1] for c in costs],
                    "cagr": arr["cagr"], "sharpe": arr["sharpe"], "maxdd": arr["max_drawdown"]})
results["tests"]["R3_random_costs"] = {
    "n": len(cdf), "cagr": dist(cdf.cagr, "cagr"), "sharpe": dist(cdf.sharpe, "sharpe"),
    "maxdd": dist(cdf.maxdd, "dd"),
    "pct_cagr_over_20": round(float((cdf.cagr > 20).mean() * 100), 1),
    "pct_sharpe_over_0_9": round(float((cdf.sharpe > 0.9).mean() * 100), 1),
    "worst_cost": cdf.sort_values("cagr").iloc[0].to_dict(),
}
cdf.to_csv(OUT / "26_random_costs.csv", index=False)
print("R3 done", results["tests"]["R3_random_costs"]["cagr"])

# ---------------- R6 regime / rolling stats ----------------
# exact monthly curve for W
def exact_curve(c, start, end):
    s, e = idx_for(cube, start, end)
    off = int(cube.schedule_offsets[1]); ln = int(cube.schedule_lengths[1])
    idx = [int(i) for i in cube.rebalance_indices[off:off+ln] if s <= i <= e]
    p = param(c, s, e)
    eq = []
    for i in idx:
        j = min(i + 1, e)
        q = dict(p); q["end_date_idx"] = j
        eq.append(float(runner.engine.execute_sweep([q], cube, num_threads=1)[0]["ending_equity"]))
    return [cube.dates[min(i + 1, e)] for i in idx], np.array(eq)

dts, eq = exact_curve(W, "2018-01-01", "2026-08-31")
rets = np.diff(eq) / eq[:-1]
s_idx, e_idx = idx_for(cube, "2018-01-01", "2026-08-31")
off = int(cube.schedule_offsets[1]); ln = int(cube.schedule_lengths[1])
bidx = [int(i) for i in cube.rebalance_indices[off:off+ln] if s_idx <= i <= e_idx][1:]
b = np.array([float(cube.bench_closes[i]) for i in bidx])
brets = np.diff(b) / b[:-1]
n = min(len(rets), len(brets)); r, br = rets[:n], brets[:n]
up, down = br >= 0, br < 0
roll12 = pd.Series(r).rolling(12).apply(lambda x: np.prod(1 + x) - 1, raw=True).dropna()
results["tests"]["R6_regimes"] = {
    "bench_up_months": int(up.sum()), "bench_down_months": int(down.sum()),
    "strategy_mean_in_up_pct": round(float(r[up].mean() * 100), 2) if up.any() else None,
    "strategy_mean_in_down_pct": round(float(r[down].mean() * 100), 2) if down.any() else None,
    "strategy_win_rate_up_pct": round(float((r[up] > 0).mean() * 100), 1) if up.any() else None,
    "strategy_win_rate_down_pct": round(float((r[down] > 0).mean() * 100), 1) if down.any() else None,
    "rolling_12m": dist(roll12 * 100, "roll12"),
    "rolling_12m_pct_positive": round(float((roll12 > 0).mean() * 100), 1),
    "corr_monthly_vs_bench": round(float(np.corrcoef(r, br)[0, 1]), 3),
}
pd.DataFrame({"date": dts[1:1+n], "strategy_ret": r, "bench_ret": br}).to_csv(OUT / "27_monthly_returns.csv", index=False)
print("R6 done")

# ---------------- Low-DD search ----------------
low = []
for lb, ema, tn, buf, cap, sizing, vt in itertools.product(
        [252, 315], [150, 200, 250], [15, 20, 25], [20, 30, 40], [1, 2, 3],
        ["equal_weight", "atr_risk_parity"], [False, True]):
    low.append(dict(lookback=lb, ema=ema, top_n=tn, buffer=buf, cap=cap,
                    sizing=sizing, regime=True, vol_target=vt))
p_is = [param(c, s_is, e_is) for c in low]
p_oos = [param(c, s_oos, e_oos) for c in low]
for i, p in enumerate(p_is): p["param_id"] = i
for i, p in enumerate(p_oos): p["param_id"] = i
d1 = runner.engine.run_sweep(cube, p_is, num_threads=8)
d2 = runner.engine.run_sweep(cube, p_oos, num_threads=8)
m = pd.DataFrame({"param_id": range(len(low)),
                  "is_cagr": d1["cagr"], "is_sharpe": d1["sharpe"], "is_dd": d1["max_drawdown"], "is_calmar": d1["calmar"],
                  "is_trades": d1["total_trades"],
                  "oos_cagr": d2["cagr"], "oos_sharpe": d2["sharpe"], "oos_dd": d2["max_drawdown"], "oos_calmar": d2["calmar"],
                  "oos_trades": d2["total_trades"]})
for k in ("lookback", "ema", "top_n", "buffer", "cap", "sizing", "vol_target"):
    m[k] = [c[k] for c in low]
# Kernel max_drawdown is positive; store the portfolio convention (negative).
m["is_dd"] = -m["is_dd"].abs()
m["oos_dd"] = -m["oos_dd"].abs()
m.to_csv(OUT / "28_low_dd_grid.csv", index=False)
def pick(df, label):
    if df.empty: return None
    r = df.sort_values("score", ascending=False).iloc[0]
    out = {}
    for x in ("lookback","ema","top_n","buffer","cap","sizing","vol_target",
              "is_cagr","is_sharpe","is_dd","is_calmar","oos_cagr","oos_sharpe","oos_dd","oos_calmar","score"):
        v = r[x]
        if isinstance(v, (bool, np.bool_)):
            out[x] = bool(v)
        elif isinstance(v, (int, np.integer)):
            out[x] = int(v)
        elif isinstance(v, (float, np.floating)):
            out[x] = round(float(v), 4)
        else:
            out[x] = v
    return out
fams = {}
for name, cond in {
    "dd20_cagr": (m.is_dd > -20) & (m.oos_dd > -20),
    "dd22_cagr": (m.is_dd > -22) & (m.oos_dd > -22),
    "dd25_cagr": (m.is_dd > -25) & (m.oos_dd > -25),
    "dd20_calmar": (m.is_dd > -20) & (m.oos_dd > -20),
}.items():
    sub = m[cond & (m.is_cagr > 20) & (m.oos_cagr > 15)].copy()
    if sub.empty: fams[name] = None; continue
    sub["score"] = sub["oos_cagr"] if name.endswith("cagr") else sub["oos_cagr"] / sub["oos_dd"].abs()
    fams[name] = pick(sub, name)
results["tests"]["R7_low_dd_search"] = {"grid": len(m), "families": fams}
print("lowDD", json.dumps(fams, indent=1, default=str)[:800])

(OUT / "29_random_robustness.json").write_text(json.dumps(results, indent=2, default=str, cls=NpEncoder))
print("saved")
