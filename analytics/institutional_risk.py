"""
analytics/institutional_risk.py - Advanced Institutional Risk & Tail Engine
Project MIP Institutional Edition (BlackRock Aladdin / AQR Capital Standard)

Calculates institutional tail risk, downside dynamics, distribution moments,
and factor regression analytics beyond traditional mean-variance metrics.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


def calculate_comprehensive_risk_suite(
    returns: pd.Series | np.ndarray | List[float],
    equity_curve: Optional[pd.Series | np.ndarray | List[float]] = None,
    benchmark_returns: Optional[pd.Series | np.ndarray | List[float]] = None,
    rf_rate: float = 0.065,
    annualization_factor: int = 252,
) -> Dict[str, Any]:
    """
    Computes institutional risk, tail dynamics, and factor attribution metrics.

    Parameters:
    -----------
    returns : pd.Series or 1D array of portfolio returns (daily or periodic).
    equity_curve : Optional cumulative portfolio value / NAV series.
    benchmark_returns : Optional returns series of the benchmark.
    rf_rate : Risk-free rate (annualized, default 6.5% for Indian Sovereign 10Y).
    annualization_factor : 252 for daily, 12 for monthly, 52 for weekly.

    Returns:
    --------
    Dict containing comprehensive institutional metrics.
    """
    r = np.asarray(returns, dtype=np.float64)
    # Filter out NaNs and Infs (sanitize returns vector)
    r = r[np.isfinite(r)]

    if len(r) == 0:
        return {}

    # 1. Basic annualized return & volatility
    mean_ret = float(np.mean(r))
    cagr = float((np.prod(1.0 + r)) ** (annualization_factor / max(len(r), 1)) - 1.0) if np.all(1.0 + r > 0) else 0.0
    vol_ann = float(np.std(r, ddof=1) * np.sqrt(annualization_factor)) if len(r) > 1 else 0.0

    # 2. Downside semi-deviation & Sortino
    downside_r = r[r < 0.0]
    downside_vol_ann = (
        float(np.sqrt(np.mean(downside_r ** 2)) * np.sqrt(annualization_factor))
        if len(downside_r) > 0
        else 1e-6
    )
    sortino_ratio = float((cagr - rf_rate) / downside_vol_ann) if downside_vol_ann > 1e-6 else 0.0
    sharpe_ratio = float((cagr - rf_rate) / vol_ann) if vol_ann > 1e-6 else 0.0

    # 3. Value at Risk (Historical VaR at 95% and 99%)
    # Expressed as a positive loss percentage
    var_95 = float(-np.percentile(r, 5.0))
    var_99 = float(-np.percentile(r, 1.0))

    # 4. Conditional Value at Risk (CVaR / Expected Shortfall)
    cvar_tail_95 = r[r <= -var_95]
    cvar_95 = float(-np.mean(cvar_tail_95)) if len(cvar_tail_95) > 0 else var_95

    cvar_tail_99 = r[r <= -var_99]
    cvar_99 = float(-np.mean(cvar_tail_99)) if len(cvar_tail_99) > 0 else var_99

    # 5. Equity curve & Drawdown analytics
    if equity_curve is not None:
        eq = np.asarray(equity_curve, dtype=np.float64)
    else:
        eq = np.cumprod(1.0 + r) * 100.0

    peaks = np.maximum.accumulate(eq)
    drawdowns = (eq - peaks) / np.maximum(peaks, 1e-6)
    max_drawdown = float(abs(np.min(drawdowns))) if len(drawdowns) > 0 else 0.0
    calmar_ratio = float(cagr / max_drawdown) if max_drawdown > 1e-6 else 0.0

    # 6. Ulcer Index (UI) and Ulcer Performance Index (UPI / Martin Ratio)
    # UI = sqrt( mean( (Drawdown * 100)^2 ) )
    dd_pct = drawdowns * 100.0
    ulcer_index = float(np.sqrt(np.mean(dd_pct ** 2))) if len(dd_pct) > 0 else 0.0
    excess_cagr = cagr - rf_rate
    if ulcer_index > 1e-4:
        ulcer_performance_index = float(excess_cagr / (ulcer_index / 100.0))
    else:
        ulcer_performance_index = 999.0 if excess_cagr > 0.0 else (0.0 if abs(excess_cagr) <= 1e-6 else -999.0)

    # 7. Discrete Drawdown Episodes & Burke Ratio
    # Identify distinct drawdown valley troughs
    drawdown_episodes: List[float] = []
    in_dd = False
    current_trough = 0.0
    for dd in drawdowns:
        if dd < -1e-4:
            in_dd = True
            if dd < current_trough:
                current_trough = dd
        else:
            if in_dd:
                drawdown_episodes.append(abs(current_trough))
                in_dd = False
                current_trough = 0.0
    if in_dd:
        drawdown_episodes.append(abs(current_trough))

    burke_denominator = float(np.sqrt(sum(d ** 2 for d in drawdown_episodes))) if drawdown_episodes else 0.0
    if burke_denominator > 1e-6:
        burke_ratio = float(excess_cagr / burke_denominator)
    else:
        burke_ratio = 999.0 if excess_cagr > 0.0 else (0.0 if abs(excess_cagr) <= 1e-6 else -999.0)

    # Drawdown Duration (sessions)
    max_dd_duration = 0
    cur_dd_duration = 0
    all_dd_durations: List[int] = []
    for dd in drawdowns:
        if dd < -1e-4:
            cur_dd_duration += 1
            if cur_dd_duration > max_dd_duration:
                max_dd_duration = cur_dd_duration
        else:
            if cur_dd_duration > 0:
                all_dd_durations.append(cur_dd_duration)
                cur_dd_duration = 0
    if cur_dd_duration > 0:
        all_dd_durations.append(cur_dd_duration)

    avg_recovery_duration = float(np.mean(all_dd_durations)) if all_dd_durations else 0.0

    # 8. Asymmetric Return Ratios: Omega, Gain-to-Pain, Tail Ratio
    # Omega ratio relative to zero or rf threshold
    threshold = rf_rate / annualization_factor
    upside_excess = np.maximum(r - threshold, 0.0)
    downside_excess = np.maximum(threshold - r, 0.0)
    sum_upside = float(np.sum(upside_excess))
    sum_downside = float(np.sum(downside_excess))
    if sum_downside > 1e-8:
        omega_ratio = float(sum_upside / sum_downside)
    elif sum_upside > 1e-8:
        omega_ratio = 999.0
    else:
        omega_ratio = 0.0

    # Gain-to-Pain (Schwager)
    positive_gains = float(np.sum(np.maximum(r, 0.0)))
    negative_losses = float(np.sum(np.abs(np.minimum(r, 0.0))))
    if negative_losses > 1e-8:
        gain_to_pain_ratio = float(positive_gains / negative_losses)
    elif positive_gains > 1e-8:
        gain_to_pain_ratio = 999.0
    else:
        gain_to_pain_ratio = 0.0

    # Tail Ratio: 95th percentile / abs(5th percentile)
    p95 = float(np.percentile(r, 95.0))
    p05 = float(np.percentile(r, 5.0))
    tail_ratio = float(abs(p95) / abs(p05)) if abs(p05) > 1e-8 else 1.0

    # 9. Skewness and Excess Kurtosis
    if len(r) > 2 and vol_ann > 1e-6:
        std_r = np.std(r, ddof=1)
        z = (r - mean_ret) / std_r
        skewness = float(np.mean(z ** 3))
        kurtosis = float(np.mean(z ** 4) - 3.0)  # Excess kurtosis
    else:
        skewness = 0.0
        kurtosis = 0.0

    # 10. Benchmark Regression & Risk Decomposition
    tracking_error = 0.0
    information_ratio = 0.0
    beta = 1.0
    alpha_ann = 0.0
    r_squared = 0.0
    systematic_risk_pct = 0.0
    specific_risk_pct = 100.0

    if benchmark_returns is not None:
        if isinstance(returns, (pd.Series, pd.DataFrame)) and isinstance(benchmark_returns, (pd.Series, pd.DataFrame)):
            s_ret = returns if isinstance(returns, pd.Series) else returns.iloc[:, 0]
            s_bm = benchmark_returns if isinstance(benchmark_returns, pd.Series) else benchmark_returns.iloc[:, 0]
            df_aligned = pd.DataFrame({"r": s_ret, "bm": s_bm}).dropna()
            r_clean = df_aligned["r"].to_numpy(dtype=np.float64)
            bm_clean = df_aligned["bm"].to_numpy(dtype=np.float64)
        else:
            r_raw = np.asarray(returns, dtype=np.float64)
            bm_raw = np.asarray(benchmark_returns, dtype=np.float64)
            valid_len = min(len(r_raw), len(bm_raw))
            r_sub = r_raw[:valid_len]
            bm_sub = bm_raw[:valid_len]
            mask = np.isfinite(r_sub) & np.isfinite(bm_sub)
            r_clean = r_sub[mask]
            bm_clean = bm_sub[mask]

        if len(r_clean) > 5 and np.var(bm_clean) > 1e-8:
            bm_cagr = float((np.prod(1.0 + bm_clean)) ** (annualization_factor / len(bm_clean)) - 1.0) if np.all(1.0 + bm_clean > 0) else 0.0
            excess_diff = r_clean - bm_clean
            tracking_error = float(np.std(excess_diff, ddof=1) * np.sqrt(annualization_factor))
            information_ratio = float((cagr - bm_cagr) / tracking_error) if tracking_error > 1e-6 else 0.0

            # OLS Regression: r_p = alpha + beta * r_bm
            cov_mat = np.cov(r_clean, bm_clean)
            beta = float(cov_mat[0, 1] / cov_mat[1, 1])
            alpha_daily = float(np.mean(r_clean) - beta * np.mean(bm_clean))
            alpha_ann = float(alpha_daily * annualization_factor)

            corr = float(np.corrcoef(r_clean, bm_clean)[0, 1])
            r_squared = float(corr ** 2) if not math.isnan(corr) else 0.0
            systematic_risk_pct = float(r_squared * 100.0)
            specific_risk_pct = float((1.0 - r_squared) * 100.0)

    return {
        "cagr": round(cagr, 4),
        "annualized_volatility": round(vol_ann, 4),
        "downside_volatility": round(downside_vol_ann, 4),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "sortino_ratio": round(sortino_ratio, 2),
        "calmar_ratio": round(calmar_ratio, 2),
        "max_drawdown": round(max_drawdown, 4),
        "var_95": round(var_95, 4),
        "var_99": round(var_99, 4),
        "cvar_95": round(cvar_95, 4),
        "cvar_99": round(cvar_99, 4),
        "ulcer_index": round(ulcer_index, 2),
        "ulcer_performance_index": round(ulcer_performance_index, 2),
        "burke_ratio": round(burke_ratio, 2),
        "omega_ratio": round(omega_ratio, 2),
        "gain_to_pain_ratio": round(gain_to_pain_ratio, 2),
        "tail_ratio": round(tail_ratio, 2),
        "skewness": round(skewness, 2),
        "kurtosis": round(kurtosis, 2),
        "max_drawdown_duration_sessions": int(max_dd_duration),
        "avg_recovery_duration_sessions": round(avg_recovery_duration, 1),
        "tracking_error": round(tracking_error, 4),
        "information_ratio": round(information_ratio, 2),
        "beta": round(beta, 2),
        "alpha_annualized": round(alpha_ann, 4),
        "r_squared": round(r_squared, 4),
        "systematic_risk_pct": round(systematic_risk_pct, 1),
        "specific_risk_pct": round(specific_risk_pct, 1),
    }
