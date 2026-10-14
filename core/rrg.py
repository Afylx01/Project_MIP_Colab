"""
Project MIP Pydroid 3: Relative Rotation Graph (RRG) Engine
Directive: DIR-PROD-PYDROID3-PORT-01

Implements the Julius de Kempenaer (JdK) Relative Rotation Graph model:
  - RS = Stock_Price / Benchmark_Price
  - RS-Ratio = 100.0 * (RS / SMA_50(RS))
  - RS-Momentum = 100.0 * (RS-Ratio / SMA_10(RS-Ratio))
  - Quadrant Classification:
      - LEADING:    RS-Ratio >= 100 and RS-Momentum >= 100 (🟢 OUTPERFORM)
      - WEAKENING:  RS-Ratio >= 100 and RS-Momentum < 100 (🟡 DECELERATING)
      - LAGGING:    RS-Ratio < 100 and RS-Momentum < 100  (🔴 UNDERPERFORM)
      - IMPROVING:  RS-Ratio < 100 and RS-Momentum >= 100 (🟢 ACCELERATING)
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Dict


def classify_quadrant(rs_ratio: float, rs_momentum: float) -> str:
    """Classifies (RS-Ratio, RS-Momentum) into one of four RRG quadrants."""
    if rs_ratio >= 100.0 and rs_momentum >= 100.0:
        return "LEADING"
    elif rs_ratio >= 100.0 and rs_momentum < 100.0:
        return "WEAKENING"
    elif rs_ratio < 100.0 and rs_momentum < 100.0:
        return "LAGGING"
    else:
        return "IMPROVING"


def compute_rrg_metrics(
    df: pd.DataFrame,
    ratio_period: int = 50,
    momentum_period: int = 10,
    benchmark_col: str = "benchmark_close"
) -> pd.DataFrame:
    """
    Computes RS, RS-Ratio, RS-Momentum, and Quadrant across multi-symbol DataFrame.
    Expects df to have columns: ['symbol', 'date', 'close', benchmark_col].
    Sorted by [symbol, date].
    """
    out = df.copy()
    if benchmark_col not in out.columns:
        out[benchmark_col] = 1.0

    # Avoid division by zero
    bench = out[benchmark_col].replace(0.0, np.nan)
    out["rrg_raw_rs"] = out["close"] / bench

    # RS-Ratio
    out["rrg_rs_sma"] = out.groupby("symbol")["rrg_raw_rs"].transform(
        lambda s: s.rolling(ratio_period, min_periods=min(10, len(s))).mean()
    )
    denom_ratio = out["rrg_rs_sma"].replace(0.0, np.nan)
    out["rrg_rs_ratio"] = 100.0 * (out["rrg_raw_rs"] / denom_ratio).fillna(100.0)

    # RS-Momentum
    out["rrg_ratio_sma"] = out.groupby("symbol")["rrg_rs_ratio"].transform(
        lambda s: s.rolling(momentum_period, min_periods=min(3, len(s))).mean()
    )
    denom_mom = out["rrg_ratio_sma"].replace(0.0, np.nan)
    out["rrg_rs_momentum"] = 100.0 * (out["rrg_rs_ratio"] / denom_mom).fillna(100.0)

    # Quadrant
    out["rrg_quadrant"] = [
        classify_quadrant(r, m)
        for r, m in zip(out["rrg_rs_ratio"], out["rrg_rs_momentum"])
    ]

    return out
