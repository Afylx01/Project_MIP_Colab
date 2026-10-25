#!/usr/bin/env python3
"""A/B the three next-gen overlays on the verified PIT universe.

Overlays (strategy filters unchanged; each is an additive filter/weight):
  residual_momentum  - Blitz et al. residual momentum, composite 0.6*residual + 0.4*volar ranking
  vol_targeting      - EWMA vol scalar (12% target, 0.2-1.0 exposure) with regime cash shield
  delivery_veto      - SMFI microstructure gate (veto buys on heavy distribution)

Runs the 2^3 combinations for the canonical and the best grid configuration on
2018-01-01..2026-08-31, NIFTY500 PIT, C99 kernel.

Output: reports/verified/overlay_matrix.csv
"""
from __future__ import annotations

import itertools
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brute_force.grid import (  # noqa: E402
    CANONICAL_BASELINE,
    CANONICAL_FILTER_FLAGS,
    FILTER_DELIVERY_VETO,
    FILTER_RESIDUAL_MOM,
    FILTER_VOL_TARGETING,
    SCHEDULE_MAP,
)
from brute_force.runner import BruteForceCampaignRunner  # noqa: E402

BASE = {
    "canonical_20_252_200_0.80_s2": dict(top_n=20, lookback=252, ema=200, retrace=0.80, sector=2),
    "best_10_189_250_0.80_s2": dict(top_n=10, lookback=189, ema=250, retrace=0.80, sector=2),
}


def param(cube, cfg, flags, pid, label):
    p = CANONICAL_BASELINE.copy()
    p.update({
        "param_id": pid, "tier": "OVERLAY", "label": label,
        "schedule": "monthly", "schedule_idx": SCHEDULE_MAP["monthly"],
        "start_date": "2018-01-01", "end_date": "2026-08-31",
        "start_date_idx": min(cube.date_to_idx[d] for d in cube.dates if d >= "2018-01-01"),
        "end_date_idx": max(cube.date_to_idx[d] for d in cube.dates if d <= "2026-08-31"),
        "lookback": cfg["lookback"],
        "lookback_idx": int(min(range(len(cube.lookback_values)),
                                key=lambda i: abs(cube.lookback_values[i] - cfg["lookback"]))),
        "ema_trend": cfg["ema"], "ema_idx": int(min(range(len(cube.ema_span_values)),
                                key=lambda i: abs(cube.ema_span_values[i] - cfg["ema"]))),
        "retrace_threshold": cfg["retrace"], "top_n": cfg["top_n"],
        "exit_buffer_rank": 40, "max_per_sector": cfg["sector"],
        "sizing_mode": "atr_risk_parity", "risk_per_trade_pct": 1.0,
        "filter_flags": flags,
    })
    return p


def main() -> int:
    t0 = time.time()
    runner = BruteForceCampaignRunner(base_dir=ROOT)
    cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")
    print(f"cube {time.time()-t0:.0f}s")
    params, pid = [], 0
    for base_name, cfg in BASE.items():
        for resid, volt, deliv in itertools.product([0, 1], repeat=3):
            flags = CANONICAL_FILTER_FLAGS
            if resid: flags |= FILTER_RESIDUAL_MOM
            if volt: flags |= FILTER_VOL_TARGETING
            if deliv: flags |= FILTER_DELIVERY_VETO
            pid += 1
            label = f"{base_name}|R{resid}V{volt}D{deliv}"
            p = param(cube, cfg, flags, pid, label)
            p.update({"residual": resid, "vol_target": volt, "delivery": deliv, "base": base_name})
            params.append(p)
    df = runner.run_sweep(params, num_threads=4)
    out = ROOT / "reports" / "verified" / "overlay_matrix.csv"
    df.to_csv(out, index=False)
    cols = ["base", "residual", "vol_target", "delivery", "cagr", "sharpe", "max_drawdown", "total_trades"]
    print(df[cols].sort_values(["base", "sharpe"], ascending=[True, False]).round(3).to_string(index=False))
    print(f"wrote {out} in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
