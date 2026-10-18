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

    stock_df = pd.DataFrame(stock_mat, index=stock_returns.index, columns=stock_returns.columns)
    s_bm = pd.Series(bench_excess, index=stock_returns.index)

    # Rolling benchmark variance & mean
    bench_var = s_bm.rolling(lookback, min_periods=min(50, lookback)).var()
    bench_mean = s_bm.rolling(lookback, min_periods=min(50, lookback)).mean()

    effective_lb = lookback - skip_recent
    if effective_lb <= 0:
        effective_lb = lookback

    # Vectorized 2D rolling stock mean & covariance across all columns
    stock_mean = stock_df.rolling(lookback, min_periods=min(50, lookback)).mean()
    rolling_cov = stock_df.rolling(lookback, min_periods=min(50, lookback)).cov(s_bm)

    # Vectorized Beta and Alpha
    b_var_mat = np.tile(bench_var.to_numpy()[:, None], (1, N))
    b_mean_mat = np.tile(bench_mean.to_numpy()[:, None], (1, N))
    bm_excess_mat = np.tile(bench_excess[:, None], (1, N))

    cov_mat = rolling_cov.to_numpy()
    safe_b_var = np.where(b_var_mat > 1e-8, b_var_mat, 1.0)
    beta = np.where(b_var_mat > 1e-8, cov_mat / safe_b_var, 1.0)
    beta = np.nan_to_num(beta, nan=1.0, posinf=1.0, neginf=1.0)
    alpha = stock_mean.to_numpy() - (beta * b_mean_mat)

    # Residual return series: eps_t = R_i,t - (alpha + beta * R_m,t)
    eps = stock_mat - (alpha + beta * bm_excess_mat)
    eps_df = pd.DataFrame(eps, index=stock_returns.index, columns=stock_returns.columns)

    # Rolling standard deviation of residuals (vectorized across all columns)
    eps_std = eps_df.rolling(lookback, min_periods=min(50, lookback)).std().to_numpy()
    eps_std = np.clip(eps_std, 1e-4, None)

    # Intermediate momentum sum: excluding the most recent skip_recent sessions
    shifted_eps = eps_df.shift(skip_recent)
    eps_sum = shifted_eps.rolling(effective_lb, min_periods=min(30, effective_lb)).sum().to_numpy()

    with np.errstate(divide="ignore", invalid="ignore"):
        res_raw = eps_sum / (eps_std * np.sqrt(effective_lb))
    res_clean = np.nan_to_num(res_raw, nan=0.0, posinf=0.0, neginf=0.0)
    res_score = np.clip(res_clean, -5.0, 5.0)
    return pd.DataFrame(res_score, index=stock_returns.index, columns=stock_returns.columns)


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
