"""
nextgen/risk_statistics.py
Institutional Quantitative Risk & Statistical Deflation Subsystem.
Implements Bailey & López de Prado (2014):
1. Probabilistic Sharpe Ratio (PSR) accounting for skewness, kurtosis, and sample size.
2. Deflated Sharpe Ratio (DSR) correcting for selection bias across K multiple backtest trials.
3. Factor Return Attribution (Market Beta, Residual Alpha, Information Ratio).
"""

import math
from typing import Dict, Any, Optional, Union
import numpy as np
import pandas as pd


# Euler-Mascheroni constant
EULER_MASCHERONI = 0.57721566490153286


def _normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function (Phi)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_ppf(p: float) -> float:
    """
    Standard normal percent point function (inverse CDF) using Abramowitz & Stegun
    rational approximation. High precision (error < 4.5e-4).
    """
    if p <= 0.0:
        return -8.0
    if p >= 1.0:
        return 8.0
    if p == 0.5:
        return 0.0

    # Symmetry
    if p < 0.5:
        return -_normal_ppf(1.0 - p)

    t = math.sqrt(-2.0 * math.log(1.0 - p))
    c0 = 2.515517
    c1 = 0.802853
    c2 = 0.010328
    d1 = 1.432788
    d2 = 0.189269
    d3 = 0.001308
    return t - ((c2 * t + c1) * t + c0) / (((d3 * t + d2) * t + d1) * t + 1.0)


def compute_sample_moments(returns: Union[pd.Series, np.ndarray]) -> Dict[str, float]:
    """
    Computes mean, standard deviation, skewness (gamma_3), and Pearson kurtosis (gamma_4).
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 3:
        return {"n": float(n), "mean": 0.0, "std": 0.0, "skew": 0.0, "kurtosis": 3.0}

    mean = float(np.mean(arr))
    var = float(np.var(arr, ddof=1))
    std = math.sqrt(var) if var > 0.0 else 0.0

    # Standardized moments
    if std > 0.0:
        z = (arr - mean) / std
        skew = float(np.mean(z ** 3))
        kurtosis = float(np.mean(z ** 4))  # Pearson kurtosis (normal = 3.0)
    else:
        skew = 0.0
        kurtosis = 3.0

    return {
        "n": float(n),
        "mean": mean,
        "std": std,
        "skew": skew,
        "kurtosis": kurtosis,
    }


def compute_probabilistic_sharpe_ratio(
    returns: Union[pd.Series, np.ndarray],
    benchmark_sr: float = 0.0,
    annualization_factor: int = 252,
) -> Optional[float]:
    """
    Computes the Probabilistic Sharpe Ratio (PSR) of Bailey & López de Prado (2012/2014).
    Accounts for non-normality: return skewness (gamma_3) and fat tails (gamma_4).
    Dual contract: returns 0.0 for degenerate zero-variance series (std <= 0.0 or n < 3);
    returns None if the variance or denominator is undefined or non-finite.

    Note on Excess Returns:
        When testing against benchmark_sr = 0.0, the input returns series must represent
        excess returns over the risk-free rate (i.e. R_t - R_{f,t}). Passing raw returns
        evaluates total return significance rather than risk-free hurdle alpha.
    
    Formula:
        PSR(SR*) = Phi( (SR - SR*) * sqrt(N - 1) / sqrt(1 - gamma_3 * SR + (gamma_4 - 1)/4 * SR^2) )
    """
    moments = compute_sample_moments(returns)
    n = moments["n"]
    if n < 3 or not np.isfinite(moments["std"]) or moments["std"] <= 0.0:
        return 0.0

    # Unannualized daily Sharpe ratio
    sr = moments["mean"] / moments["std"]
    sr_star = benchmark_sr / math.sqrt(annualization_factor)

    skew = moments["skew"]
    kurt = moments["kurtosis"]

    denom_sq = 1.0 - skew * sr + ((kurt - 1.0) / 4.0) * (sr ** 2)
    if not np.isfinite(denom_sq) or denom_sq <= 0.0:
        return None
    denom = math.sqrt(denom_sq)

    z_stat = (sr - sr_star) * math.sqrt(n - 1.0) / denom
    psr = _normal_cdf(z_stat)
    return float(np.clip(psr, 0.0, 1.0))


def compute_expected_max_sharpe_ratio(
    n_trials: int,
    var_sr: float = 1.0,
) -> float:
    """
    Computes expected maximum Sharpe Ratio across K independent trials under the null hypothesis (SR=0).
    Bailey & López de Prado (2014):
        SR_0 = sqrt(Var[SR]) * [ (1 - gamma) * Phi^{-1}(1 - 1/K) + gamma * Phi^{-1}(1 - 1/(K * e)) ]
    """
    if not np.isfinite(var_sr) or var_sr <= 0.0:
        raise ValueError(f"var_sr must be positive, got {var_sr}")

    if n_trials <= 1:
        return 0.0

    k = float(n_trials)
    p1 = 1.0 - (1.0 / k)
    p2 = 1.0 - (1.0 / (k * math.e))

    z1 = _normal_ppf(p1)
    z2 = _normal_ppf(p2)

    sr_0_std = (1.0 - EULER_MASCHERONI) * z1 + EULER_MASCHERONI * z2
    sigma_sr = math.sqrt(var_sr)
    return float(sr_0_std * sigma_sr)


def compute_deflated_sharpe_ratio(
    returns: Union[pd.Series, np.ndarray],
    n_trials: int = 1,
    annualization_factor: int = 252,
) -> Optional[float]:
    """
    Computes Deflated Sharpe Ratio (DSR) by testing observed Sharpe against the expected
    maximum Sharpe ratio across K multiple parameter testing trials.
    Dual contract: returns 0.0 for degenerate zero-variance series (std <= 0.0 or n < 3);
    returns None if the variance or denominator is undefined or non-finite.

    Note on Excess Returns:
        When testing against the null hypothesis (SR=0), the input returns series must represent
        excess returns over the risk-free rate (i.e. R_t - R_{f,t}). Passing raw returns
        evaluates whether gross returns exceed zero, inflating DSR/PSR.
    
    Formula:
        DSR = PSR(SR_0)
        where SR_0 = E[max_K(SR)]
    """
    if n_trials <= 1:
        return compute_probabilistic_sharpe_ratio(returns, benchmark_sr=0.0, annualization_factor=annualization_factor)

    moments = compute_sample_moments(returns)
    n = moments["n"]
    if n < 3 or not np.isfinite(moments["std"]) or moments["std"] <= 0.0:
        return 0.0

    sr_daily = moments["mean"] / moments["std"]
    sr_ann = sr_daily * math.sqrt(annualization_factor)

    # Standard error variance of the Sharpe ratio estimator
    skew = moments["skew"]
    kurt = moments["kurtosis"]
    var_sr_unann = (1.0 - skew * sr_daily + ((kurt - 1.0) / 4.0) * (sr_daily ** 2)) / max(n - 1.0, 1.0)
    var_sr_ann = var_sr_unann * annualization_factor
    if not np.isfinite(var_sr_ann) or var_sr_ann <= 0.0:
        return None

    # Compute expected maximum annualized SR under K trials
    sr_0_ann = compute_expected_max_sharpe_ratio(n_trials=n_trials, var_sr=var_sr_ann)

    # Compute PSR testing whether observed SR exceeds SR_0 hurdle
    return compute_probabilistic_sharpe_ratio(returns, benchmark_sr=sr_0_ann, annualization_factor=annualization_factor)


def compute_factor_return_attribution(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    annualization_factor: int = 252,
) -> Dict[str, float]:
    """
    Decomposes strategy returns into Market Beta Return and Idiosyncratic Alpha Return.
    
    Returns:
        beta: Regression sensitivity to benchmark
        alpha_annualized: Annualized excess idiosyncratic return
        information_ratio: Annualized Alpha / Tracking Error
        total_return: Portfolio cumulative return
        benchmark_return: Benchmark cumulative return
    """
    aligned = pd.DataFrame({"port": portfolio_returns, "bench": benchmark_returns}).dropna()
    if len(aligned) < 5:
        return {
            "beta": 1.0,
            "alpha_annualized": 0.0,
            "tracking_error_annualized": 0.0,
            "information_ratio": 0.0,
            "total_return": 0.0,
            "benchmark_return": 0.0,
        }

    cov = float(np.cov(aligned["port"], aligned["bench"])[0, 1])
    var_bench = float(np.var(aligned["bench"], ddof=1))
    beta = (cov / var_bench) if var_bench > 0 else 1.0

    # Alpha series: R_p - beta * R_m
    alpha_daily = aligned["port"] - beta * aligned["bench"]
    alpha_mean = float(np.mean(alpha_daily))
    alpha_ann = alpha_mean * annualization_factor

    te_daily = float(np.std(alpha_daily, ddof=1))
    te_ann = te_daily * math.sqrt(annualization_factor)
    ir = (alpha_ann / te_ann) if te_ann > 0 else 0.0

    cum_port = float(np.prod(1.0 + aligned["port"]) - 1.0)
    cum_bench = float(np.prod(1.0 + aligned["bench"]) - 1.0)

    return {
        "beta": round(beta, 4),
        "alpha_annualized": round(alpha_ann, 4),
        "tracking_error_annualized": round(te_ann, 4),
        "information_ratio": round(ir, 4),
        "total_return": round(cum_port, 4),
        "benchmark_return": round(cum_bench, 4),
    }
