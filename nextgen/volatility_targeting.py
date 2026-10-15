"""
volatility_targeting.py - Feature 3: Continuous Volatility Targeting & Dynamic Cash Shield
References:
- Barroso, P., & Santa-Clara, P. (2015). Momentum Has Its Moments. Journal of Financial Economics.
- Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. The Journal of Finance.
- Harvey, C. R., et al. (Man AHL, 2018). The Impact of Volatility Targeting. Journal of Portfolio Management.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Union
import math
import numpy as np
import pandas as pd


@dataclass
class VolatilityTargetConfig:
    target_annual_vol: float = 0.12
    lambda_decay: float = 0.94
    min_exposure: float = 0.20
    max_exposure: float = 1.00
    breadth_weight: float = 0.50


def compute_ewma_realized_volatility(
    returns_series: pd.Series,
    lambda_decay: float = 0.94,
) -> pd.Series:
    """
    Computes Exponentially Weighted Moving Average (EWMA) realized variance & annualized volatility.
    sigma_t^2 = lambda * sigma_{t-1}^2 + (1 - lambda) * R_t^2
    """
    vals = np.nan_to_num(returns_series.to_numpy(dtype=np.float64), nan=0.0)
    T = len(vals)
    var_ewma = np.zeros(T, dtype=np.float64)

    # Initial variance from first 20 observations or default 0.12^2 / 252
    init_var = np.var(vals[:min(20, T)]) if T > 5 else (0.12 ** 2 / 252.0)
    if not math.isfinite(init_var) or init_var <= 0:
        init_var = 0.12 ** 2 / 252.0

    current_var = init_var
    for t in range(T):
        r_sq = vals[t] ** 2
        current_var = (lambda_decay * current_var) + ((1.0 - lambda_decay) * r_sq)
        var_ewma[t] = current_var

    ann_vol = np.sqrt(np.maximum(var_ewma, 1e-8)) * np.sqrt(252.0)
    return pd.Series(ann_vol, index=returns_series.index)


def compute_volatility_target_scalar(
    returns_series: pd.Series,
    target_vol: float = 0.12,
    min_exposure: float = 0.20,
    max_exposure: float = 1.00,
    lambda_decay: float = 0.94,
) -> pd.Series:
    """
    Computes dynamic continuous volatility target scaling factor:
    w_t = clip(target_vol / realized_vol_t, min_exposure, max_exposure)
    """
    ann_vol = compute_ewma_realized_volatility(returns_series, lambda_decay=lambda_decay)
    scalar = np.clip(target_vol / np.maximum(ann_vol, 0.01), min_exposure, max_exposure)
    return scalar


def compute_dynamic_cash_shield_scalar(
    is_bull_regime: bool,
    realized_vol: float,
    target_vol: float = 0.12,
    breadth_ratio: float = 1.0,
    min_exposure: float = 0.20,
    max_exposure: float = 1.00,
) -> float:
    """
    Computes composite portfolio exposure scalar S_t:
    If is_bull_regime is False (Close < 20 EMA) -> returns 0.0 (Strict Fail-Closed Invariant).
    Otherwise -> returns clip(target_vol / realized_vol) * sqrt(clip(breadth_ratio)).
    """
    if not is_bull_regime:
        return 0.0  # 100% Cash Shield in Bear Regime

    if not math.isfinite(realized_vol) or realized_vol <= 0:
        realized_vol = target_vol
    if not math.isfinite(breadth_ratio):
        breadth_ratio = 1.0

    vol_scalar = np.clip(target_vol / max(realized_vol, 0.01), min_exposure, max_exposure)
    b_clamped = np.clip(breadth_ratio, 0.10, 1.0)
    composite_scalar = float(vol_scalar * np.sqrt(b_clamped))
    return float(np.clip(composite_scalar, min_exposure, max_exposure))


def scale_position_quantities_by_shield(
    nominal_quantities: Dict[str, int],
    shield_scalar: float,
) -> Dict[str, int]:
    """
    Scales whole-share integer order quantities down by shield scalar.
    Enforces strict integer whole shares (zero fractional shares).
    """
    if not math.isfinite(shield_scalar) or shield_scalar <= 0.0:
        return {sym: 0 for sym in nominal_quantities}

    clamped_scalar = min(1.0, max(0.0, shield_scalar))
    scaled = {}
    for sym, q in nominal_quantities.items():
        scaled[sym] = int(math.floor(q * clamped_scalar))
    return scaled
