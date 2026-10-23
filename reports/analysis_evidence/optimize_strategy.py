import sys, json, time, itertools
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (CANONICAL_BASELINE, FILTER_RETRACE, FILTER_TREND,
                              FILTER_RS, FILTER_REGIME, FILTER_SECTOR_CAP,
                              LOOKBACK_VALUES, EMA_SPAN_VALUES, SCHEDULE_MAP)

OUT = ROOT / "reports" / "analysis_evidence"

WINDOWS = {
    "is_2016_2021": ("2016-01-01", "2021-12-31"),
    "oos_2022_2026": ("2022-01-01", "2026-08-31"),
    "full_2016_2026": ("2016-01-01", "2026-08-31"),
    "long_2008_2026": ("2008-01-01", "2026-08-31"),
}

t0 = time.time()
runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
print("cube_sec", round(time.time() - t0, 1), "dates", cube.num_dates, "symbols", cube.num_symbols)

def idx_for(start, end):
    s = min(cube.date_to_idx[d] for d in cube.dates if d >= start)
    e = max(cube.date_to_idx[d] for d in cube.dates if d <= end)
    return s, e

# 12,800-configuration grid
grid = []
pid = 0
for lb, ema, top_n, buf, cap, sizing, regime in itertools.product(
        LOOKBACK_VALUES, EMA_SPAN_VALUES, [10, 15, 20, 25, 30],
        [20, 30, 40, 50, 60], [1, 2, 3, 99],
        ["atr_risk_parity", "equal_weight"], [True, False]):
    flags = FILTER_RETRACE | FILTER_TREND | FILTER_RS
    if regime:
        flags |= FILTER_REGIME
    if cap < 90:
        flags |= FILTER_SECTOR_CAP
    p = CANONICAL_BASELINE.copy()
    p.update({
        "param_id": pid,
        "schedule": "monthly", "schedule_idx": SCHEDULE_MAP["monthly"],
        "lookback": lb, "lookback_idx": LOOKBACK_VALUES.index(lb),
        "ema_trend": ema, "ema_idx": EMA_SPAN_VALUES.index(ema),
        "top_n": top_n, "exit_buffer_rank": buf, "max_per_sector": cap,
        "sizing_mode": sizing, "filter_flags": flags,
        "initial_capital": 1_000_000.0, "friction_bps": 15.0, "slippage_bps": 5.0,
        "risk_per_trade_pct": 1.0,
    })
    grid.append(p)
    pid += 1
print("grid_size", len(grid))

frames = {}
for name, (s, e) in WINDOWS.items():
    s_idx, e_idx = idx_for(s, e)
    params = []
    for p in grid:
        q = p.copy()
        q["start_date"], q["end_date"] = s, e
        q["start_date_idx"], q["end_date_idx"] = s_idx, e_idx
        params.append(q)
    t = time.perf_counter()
    df = runner.engine.run_sweep(cube, params, num_threads=8)
    df["param_id"] = [p["param_id"] for p in params]
    frames[name] = df
    print(f"{name}: {len(df)} rows in {time.perf_counter()-t:.1f}s | valid={int((df['status']=='VALID').sum())}")

# Attach parameters
meta = pd.DataFrame([{k: p[k] for k in (
    "param_id","lookback","ema_trend","top_n","exit_buffer_rank","max_per_sector",
    "sizing_mode","filter_flags")} for p in grid])
meta["regime"] = [bool(p["filter_flags"] & FILTER_REGIME) for p in grid]
meta["sector_cap_on"] = [bool(p["filter_flags"] & FILTER_SECTOR_CAP) for p in grid]
for name in frames:
    frames[name] = frames[name].merge(meta, on="param_id", how="left")

# Join IS and OOS
isdf = frames["is_2016_2021"][["param_id","cagr","sharpe","sortino","max_drawdown","calmar",
                               "win_rate","profit_factor","total_trades","status"]].rename(
    columns={c: f"is_{c}" for c in ("cagr","sharpe","sortino","max_drawdown","calmar",
                                    "win_rate","profit_factor","total_trades","status")})
oosdf = frames["oos_2022_2026"][["param_id","cagr","sharpe","sortino","max_drawdown","calmar",
                                 "win_rate","profit_factor","total_trades","status"]].rename(
    columns={c: f"oos_{c}" for c in ("cagr","sharpe","sortino","max_drawdown","calmar",
                                     "win_rate","profit_factor","total_trades","status")})
joined = meta.merge(isdf, on="param_id").merge(oosdf, on="param_id")
joined = joined[(joined["is_status"] == "VALID") & (joined["oos_status"] == "VALID")]
joined["is_calmar_abs"] = joined["is_cagr"] / joined["is_max_drawdown"].abs().clip(lower=1e-6)
joined["oos_calmar_abs"] = joined["oos_cagr"] / joined["oos_max_drawdown"].abs().clip(lower=1e-6)
joined["min_calmar"] = joined[["is_calmar_abs","oos_calmar_abs"]].min(axis=1)
joined["mean_calmar"] = joined[["is_calmar_abs","oos_calmar_abs"]].mean(axis=1)
joined["mean_sharpe"] = joined[["is_sharpe","oos_sharpe"]].mean(axis=1)
joined.to_csv(OUT / "optimization_grid.csv", index=False)

def row_out(r):
    return {
        "lookback": int(r.lookback), "ema": int(r.ema_trend), "top_n": int(r.top_n),
        "buffer": int(r.exit_buffer_rank), "sector_cap": int(r.max_per_sector),
        "sizing": r.sizing_mode, "regime": bool(r.regime),
        "IS": {"cagr": round(float(r.is_cagr),2), "sharpe": round(float(r.is_sharpe),2),
               "maxdd": round(float(r.is_max_drawdown),2), "calmar": round(float(r.is_calmar_abs),2),
               "trades": int(r.is_total_trades)},
        "OOS": {"cagr": round(float(r.oos_cagr),2), "sharpe": round(float(r.oos_sharpe),2),
                "maxdd": round(float(r.oos_max_drawdown),2), "calmar": round(float(r.oos_calmar_abs),2),
                "trades": int(r.oos_total_trades)},
        "min_calmar": round(float(r.min_calmar),3), "mean_calmar": round(float(r.mean_calmar),3),
    }

# Selection families
valid = joined[(joined["is_total_trades"] >= 20) & (joined["oos_total_trades"] >= 10)]
sel = {
    "best_is_calmar": valid.sort_values("is_calmar_abs", ascending=False).iloc[0],
    "best_oos_calmar": valid.sort_values("oos_calmar_abs", ascending=False).iloc[0],
    "best_robust_min_calmar": valid.sort_values("min_calmar", ascending=False).iloc[0],
    "best_mean_calmar": valid.sort_values("mean_calmar", ascending=False).iloc[0],
    "best_mean_sharpe": valid.sort_values("mean_sharpe", ascending=False).iloc[0],
    "best_is_cagr_dd35": valid[valid["is_max_drawdown"].abs() <= 35].sort_values("is_cagr", ascending=False).iloc[0],
    "best_robust_dd30": valid[(valid["is_max_drawdown"].abs() <= 30) & (valid["oos_max_drawdown"].abs() <= 35)].sort_values("mean_calmar", ascending=False).iloc[0],
}
result = {"cube_sec": round(time.time() - t0,1), "grid_size": len(grid),
          "windows": WINDOWS, "valid_pairs": int(len(valid)),
          "selections": {k: row_out(v) for k, v in sel.items()}}

# Neighbourhood robustness for the recommended (best robust min calmar)
rec = sel["best_robust_min_calmar"]
tol = {"lookback": LOOKBACK_VALUES, "ema_trend": EMA_SPAN_VALUES,
       "top_n": [10,15,20,25,30], "exit_buffer_rank": [20,30,40,50,60]}
neigh = valid.copy()
for col, vals in tol.items():
    i = vals.index(int(rec[col]))
    allowed = {vals[j] for j in (i-1, i, i+1) if 0 <= j < len(vals)}
    neigh = neigh[neigh[col].isin(allowed)]
neigh = neigh[(neigh["max_per_sector"] == rec["max_per_sector"]) &
              (neigh["sizing_mode"] == rec["sizing_mode"]) &
              (neigh["regime"] == rec["regime"])]
result["neighbourhood"] = {
    "n": int(len(neigh)),
    "is_calmar_median": round(float(neigh["is_calmar_abs"].median()), 3),
    "oos_calmar_median": round(float(neigh["oos_calmar_abs"].median()), 3),
    "oos_cagr_median": round(float(neigh["oos_cagr"].median()), 2),
    "pct_oos_positive": round(float((neigh["oos_cagr"] > 0).mean() * 100), 1),
}

print(json.dumps(result, indent=2))
(OUT / "20_optimization_grid_summary.json").write_text(json.dumps(result, indent=2))
joined.to_csv(OUT / "23_optimization_grid.csv", index=False)
