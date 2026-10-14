"""
residual_momentum.py - Feature 1: Idiosyncratic Residual Momentum & Multi-Horizon Trend Guard
References:
- Blitz, D., Huij, J., & Martens, M. (2011). Residual Momentum. Journal of Empirical Finance.
- Blitz, D., Baltussen, G., & van Vliet, P. (2020). When Equity Factors Drop Their Mask.
- Novy-Marx, R. (2012). Is Momentum Really Momentum? Journal of Financial Economics.
"""

from dataclasses import dataclass
from typing import Optional, Union
import numpy as np
import pandas as pd


@dataclass
class ResidualMomentumConfig:
    lookback_bars: int = 252
    skip_recent_bars: int = 21
    volar_weight: float = 0.40
    residual_weight: float = 0.60
    rf_rate: float = 0.065


def compute_rolling_residual_momentum(
    stock_returns: pd.DataFrame,
    bench_returns: pd.Series,
    lookback: int = 252,
    skip_recent: int = 21,
    rf_rate: float = 0.065,
) -> pd.DataFrame:
    """
    Computes rolling standardized idiosyncratic residual momentum for each stock against benchmark.
    Excludes the most recent skip_recent bars to guard against short-term reversal bounce.
    """
    if stock_returns.empty or bench_returns.empty or len(bench_returns) < (lookback + 5):
        # Fail-closed / fallback: return zeros matching stock_returns shape
        return pd.DataFrame(0.0, index=stock_returns.index, columns=stock_returns.columns)

    daily_rf = rf_rate / 252.0
    bench_excess = bench_returns.to_numpy() - daily_rf
    stock_mat = stock_returns.to_numpy() - daily_rf

    T, N = stock_mat.shape
    res_mat = np.zeros((T, N), dtype=np.float64)

    # Rolling benchmark variance
    s_bm = pd.Series(bench_excess)
    bench_var = s_bm.rolling(lookback, min_periods=min(50, lookback)).var().to_numpy()
    bench_mean = s_bm.rolling(lookback, min_periods=min(50, lookback)).mean().to_numpy()

    effective_lb = lookback - skip_recent
    if effective_lb <= 0:
        effective_lb = lookback

    for j in range(N):
        s_stock = pd.Series(stock_mat[:, j])
        stock_mean = s_stock.rolling(lookback, min_periods=min(50, lookback)).mean().to_numpy()
        rolling_cov = s_stock.rolling(lookback, min_periods=min(50, lookback)).cov(s_bm).to_numpy()

        # Beta and Alpha
        beta = np.where(bench_var > 1e-8, rolling_cov / bench_var, 1.0)
        alpha = stock_mean - (beta * bench_mean)

        # Residual return series: eps_t = R_i,t - (alpha + beta * R_m,t)
        eps = stock_mat[:, j] - (alpha + beta * bench_excess)
        s_eps = pd.Series(eps)

        # Rolling standard deviation of residuals
        eps_std = s_eps.rolling(lookback, min_periods=min(50, lookback)).std().to_numpy()
        eps_std = np.clip(eps_std, 1e-4, None)

        # Intermediate momentum sum: excluding the most recent skip_recent sessions
        shifted_eps = s_eps.shift(skip_recent)
        eps_sum = shifted_eps.rolling(effective_lb, min_periods=min(30, effective_lb)).sum().to_numpy()

        res_score = np.nan_to_num(eps_sum / (eps_std * np.sqrt(effective_lb)), nan=0.0)
        res_mat[:, j] = res_score

    return pd.DataFrame(res_mat, index=stock_returns.index, columns=stock_returns.columns)


def compute_composite_momentum_score(
    volar_scores: np.ndarray,
    residual_scores: Optional[np.ndarray] = None,
    volar_weight: float = 0.40,
    residual_weight: float = 0.60,
) -> np.ndarray:
    """
    Blends canonical Volar and Residual Volar scores.
    If residual_scores is None or unconfigured, falls back cleanly to canonical Volar.
    """
    if residual_scores is None:
        return volar_scores.copy()

    total_weight = volar_weight + residual_weight
    if total_weight <= 0:
        return volar_scores.copy()

    w_v = volar_weight / total_weight
    w_r = residual_weight / total_weight

    composite = (w_v * volar_scores) + (w_r * residual_scores)
    return composite
