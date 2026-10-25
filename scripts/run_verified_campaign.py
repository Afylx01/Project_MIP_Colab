#!/usr/bin/env python3
"""Verified parameter campaign on the rebuilt NIFTY 500 PIT membership.

Stages
------
A. Five named configurations (Fast/Balanced/Canonical/Concentrated/Broad).
B. Full grid: top_n x lookback x EMA x retrace x sector cap, monthly, 2,400 runs.
C. Schedule robustness for the ten best grid configurations (weekly/quarterly/
   half-yearly/yearly).
D. Random-duration windows (2-5 years, 2018+) for the ten best configurations.

Everything runs through the C99 tensor-cube kernel with the PIT membership mask
built from the verified table. Strategy logic (filters, ranking, exits, costs)
is unchanged; only documented parameters are varied.

Outputs: reports/verified/*.csv and campaign_summary.json.
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brute_force.grid import (  # noqa: E402
    CANONICAL_BASELINE,
    CANONICAL_FILTER_FLAGS,
    SCHEDULE_MAP,
)
from brute_force.runner import BruteForceCampaignRunner  # noqa: E402

OUT = ROOT / "reports" / "verified"
START = "2018-01-01"
END = "2026-08-31"

CONFIGS = {
    "A_fast":        dict(top_n=10, lookback=126, ema=150, retrace=0.80, sector=2),
    "B_balanced":    dict(top_n=15, lookback=189, ema=200, retrace=0.80, sector=2),
    "C_canonical":   dict(top_n=20, lookback=252, ema=200, retrace=0.80, sector=2),
    "D_concentrated":dict(top_n=25, lookback=252, ema=250, retrace=0.85, sector=2),
    "E_broad":       dict(top_n=30, lookback=315, ema=200, retrace=0.75, sector=3),
}


def idx_of(cube, day: str, side: str) -> int:
    if side == "start":
        return min([cube.date_to_idx[d] for d in cube.dates if d >= day], default=0)
    return max([cube.date_to_idx[d] for d in cube.dates if d <= day], default=cube.num_dates - 1)


def make_param(cube, *, top_n, lookback, ema, retrace, sector, schedule="monthly",
               start=START, end=END, pid=0, name="custom"):
    p = CANONICAL_BASELINE.copy()
    p.update({
        "param_id": pid,
        "tier": name,
        "schedule": schedule,
        "schedule_idx": SCHEDULE_MAP[schedule],
        "start_date": start,
        "end_date": end,
        "start_date_idx": idx_of(cube, start, "start"),
        "end_date_idx": idx_of(cube, end, "end"),
        "lookback": lookback,
        "lookback_idx": int(min(range(len(cube.lookback_values)),
                                key=lambda i: abs(cube.lookback_values[i] - lookback))),
        "ema_trend": ema,
        "ema_idx": int(min(range(len(cube.ema_span_values)),
                           key=lambda i: abs(cube.ema_span_values[i] - ema))),
        "retrace_threshold": retrace,
        "top_n": top_n,
        "exit_buffer_rank": 40,
        "max_per_sector": sector,
        "sizing_mode": "atr_risk_parity",
        "risk_per_trade_pct": 1.0,
        "filter_flags": CANONICAL_FILTER_FLAGS,
    })
    return p


def random_windows(cube, n_each=6, durations=(2.0, 3.0, 4.0, 5.0), seed=20261025):
    rng = random.Random(seed)
    lo = idx_of(cube, START, "start")
    hi = idx_of(cube, END, "end")
    out = []
    for years in durations:
        bars = int(years * 252)
        if hi - bars <= lo:
            continue
        for _ in range(n_each):
            s = rng.randint(lo, hi - bars)
            e = s + bars
            out.append({
                "start_date": cube.dates[s],
                "end_date": cube.dates[e],
                "start_date_idx": s,
                "end_date_idx": e,
                "duration_name": f"rand_{years:.0f}y_{cube.dates[s]}",
                "duration_years": years,
            })
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    runner = BruteForceCampaignRunner(base_dir=ROOT)
    cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
    print(f"cube ready in {time.time()-t0:.1f}s | {cube.num_dates} dates x {len(cube.symbols)} symbols")

    # ---- A. named configs -------------------------------------------------
    params = []
    for pid, (name, cfg) in enumerate(CONFIGS.items(), start=1):
        p = make_param(cube, pid=pid, name=name, **cfg)
        p["config_name"] = name
        params.append(p)
    cfg_df = runner.run_sweep(params, num_threads=4)
    cfg_df.to_csv(OUT / "config_matrix.csv", index=False)
    print(cfg_df[["config_name", "cagr", "sharpe", "max_drawdown", "total_trades"]].to_string(index=False))

    # ---- B. full grid -----------------------------------------------------
    grid = []
    pid = 0
    for top_n in (5, 10, 15, 20, 25, 30):
        for lb in (126, 189, 252, 315):
            for ema in (50, 100, 150, 200, 250):
                for ret in (0.70, 0.75, 0.80, 0.85, 0.90):
                    for sec in (1, 2, 3, 99):
                        pid += 1
                        p = make_param(cube, pid=pid, name="GRID", top_n=top_n, lookback=lb,
                                       ema=ema, retrace=ret, sector=sec)
                        grid.append(p)
    t1 = time.time()
    grid_df = runner.run_sweep(grid, num_threads=4)
    grid_df.to_csv(OUT / "full_grid.csv", index=False)
    print(f"full grid: {len(grid_df):,} runs in {time.time()-t1:.1f}s")

    grid_df["score"] = (
        0.45 * grid_df["sharpe"].fillna(-9)
        + 0.25 * (grid_df["cagr"].fillna(-99) / 25.0)
        + 0.20 * (1.0 - grid_df["max_drawdown"].fillna(100).abs() / 50.0)
        + 0.10 * (grid_df["profit_factor"].fillna(0).clip(upper=4) / 4.0)
    )
    ranked = grid_df[grid_df["total_trades"] >= 40].sort_values("score", ascending=False)
    top10 = ranked.head(10)

    # ---- C. schedule robustness ------------------------------------------
    sched_rows = []
    for _, r in top10.iterrows():
        for sched in ("weekly", "monthly", "quarterly", "half_yearly", "yearly"):
            sched_rows.append(make_param(
                cube, pid=len(sched_rows) + 1, name="SCHEDULE",
                top_n=int(r.top_n), lookback=float(r.lookback), ema=float(r.ema_trend),
                retrace=float(r.retrace_threshold), sector=int(r.max_per_sector),
                schedule=sched,
            ))
    sched_df = runner.run_sweep(sched_rows, num_threads=4)
    sched_df.to_csv(OUT / "schedule_matrix.csv", index=False)
    print(f"schedule matrix: {len(sched_df)} runs")

    # ---- D. random windows for top 10 ------------------------------------
    wins = random_windows(cube)
    rand_rows = []
    for _, r in top10.iterrows():
        for w in wins:
            rand_rows.append(make_param(
                cube, pid=len(rand_rows) + 1, name="RANDOM",
                top_n=int(r.top_n), lookback=float(r.lookback), ema=float(r.ema_trend),
                retrace=float(r.retrace_threshold), sector=int(r.max_per_sector),
                start=w["start_date"], end=w["end_date"],
            ))
    rand_df = runner.run_sweep(rand_rows, num_threads=4)
    rand_df.to_csv(OUT / "random_windows.csv", index=False)
    print(f"random windows: {len(rand_df)} runs over {len(wins)} windows")

    summary = {
        "generated_at_utc": pd.Timestamp.utcnow().isoformat(),
        "universe": "NIFTY500 (verified PIT membership, 17 NSE anchors)",
        "window": [START, END],
        "engine": "C99 tensor-cube kernel, PIT membership mask",
        "strategy_filters": int(CANONICAL_FILTER_FLAGS),
        "runs": {"configs": len(cfg_df), "grid": len(grid_df),
                 "schedule": len(sched_df), "random": len(rand_df)},
        "config_matrix": cfg_df.to_dict("records"),
        "top10_grid": top10.to_dict("records"),
        "schedule_matrix": sched_df[["top_n", "lookback", "ema_trend", "retrace_threshold",
                                     "max_per_sector", "schedule", "cagr", "sharpe",
                                     "max_drawdown", "total_trades"]].to_dict("records"),
        "random_windows": {
            "count": int(len(wins)),
            "top10": top10[["top_n", "lookback", "ema_trend", "retrace_threshold",
                            "max_per_sector", "cagr", "sharpe", "max_drawdown"]].to_dict("records"),
        },
    }
    (OUT / "campaign_summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(f"wrote {OUT}")
    print(f"total elapsed {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
