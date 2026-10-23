"""
tests/test_phase4_features.py
TDD Test Suite for Phase 4: Institutional Risk & Deflated Sharpe Ratio (DSR)
1. Probabilistic Sharpe Ratio (PSR) accounting for skewness and kurtosis.
2. Deflated Sharpe Ratio (DSR) correcting for selection bias across K parameter trials (Bailey & López de Prado 2014).
3. Institutional Factor Return Attribution (Market Beta, Sector Exposure, Idiosyncratic Alpha).
"""

import sys
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from nextgen.risk_statistics import (
    compute_probabilistic_sharpe_ratio,
    compute_expected_max_sharpe_ratio,
    compute_deflated_sharpe_ratio,
    compute_factor_return_attribution,
)


class TestProbabilisticSharpeRatio:
    """Verifies PSR calculations against skewness, fat tails, and benchmark hurdles."""

    def test_psr_positive_for_high_sharpe_normal_distribution(self):
        """For high Sharpe normal returns with sufficient sample size, PSR approaches 1.0."""
        np.random.seed(42)
        # 500 daily returns with positive drift (annualized SR ~ 1.8)
        daily_ret = pd.Series(np.random.normal(loc=0.0008, scale=0.01, size=500))
        psr = compute_probabilistic_sharpe_ratio(daily_ret, benchmark_sr=0.0, annualization_factor=252)
        assert 0.90 <= psr <= 1.0, f"Expected high PSR, got {psr}"

    def test_psr_penalizes_negative_skewness_and_high_kurtosis(self):
        """
        Two return series with the exact same mean and standard deviation:
        The one with negative skew and fat tails (crash risk) must receive a strictly lower PSR.
        """
        np.random.seed(42)
        n = 1000
        # Normal series
        norm_ret = np.random.normal(loc=0.0005, scale=0.01, size=n)

        # Skewed series: occasional big crashes, compensated by slightly higher regular gains
        skew_ret = norm_ret.copy()
        skew_ret[::50] -= 0.05  # Sharp negative jump
        # Adjust mean and std to match norm_ret exactly
        skew_ret = (skew_ret - np.mean(skew_ret)) / np.std(skew_ret) * np.std(norm_ret) + np.mean(norm_ret)

        psr_norm = compute_probabilistic_sharpe_ratio(pd.Series(norm_ret), benchmark_sr=0.0)
        psr_skew = compute_probabilistic_sharpe_ratio(pd.Series(skew_ret), benchmark_sr=0.0)

        assert psr_skew < psr_norm, f"Skewed PSR ({psr_skew}) should be strictly lower than normal PSR ({psr_norm})"


class TestDeflatedSharpeRatio:
    """Verifies DSR calculation across multiple parameter selection trials (Bailey & López de Prado 2014)."""

    def test_expected_max_sharpe_ratio_increases_with_trial_count(self):
        """As the number of backtest trials K increases, the expected maximum Sharpe under null increases."""
        sr_0_k10 = compute_expected_max_sharpe_ratio(n_trials=10, var_sr=1.0)
        sr_0_k100 = compute_expected_max_sharpe_ratio(n_trials=100, var_sr=1.0)
        sr_0_k1000 = compute_expected_max_sharpe_ratio(n_trials=1000, var_sr=1.0)

        assert sr_0_k10 < sr_0_k100 < sr_0_k1000, "Expected max SR must be monotonically increasing with K trials"

    def test_dsr_deflates_significance_when_many_strategies_tested(self):
        """
        A strategy with observed SR=1.2 may have DSR > 0.95 when K=1 (single test),
        but its DSR must collapse below significance when K=100 (multiple testing penalty).
        """
        np.random.seed(42)
        # Moderate Sharpe returns (~1.2 annualized)
        daily_ret = pd.Series(np.random.normal(loc=0.00045, scale=0.009, size=350))

        dsr_single = compute_deflated_sharpe_ratio(daily_ret, n_trials=1, annualization_factor=252)
        dsr_multiple = compute_deflated_sharpe_ratio(daily_ret, n_trials=100, annualization_factor=252)

        assert dsr_single > 0.80, f"Single trial DSR should be reasonably strong, got {dsr_single}"
        assert dsr_multiple < dsr_single, f"Multi-trial DSR ({dsr_multiple}) must be strictly deflated compared to single ({dsr_single})"
        assert dsr_multiple < 0.50, f"Multi-trial DSR should reflect severe selection bias penalty, got {dsr_multiple}"

    def test_deflated_sharpe_handles_nonpositive_variance(self):
        """Degenerate constant returns or non-positive variance must return finite float in [0, 1] without unhandled crash."""
        const_ret = pd.Series([0.01] * 300)
        dsr_const = compute_deflated_sharpe_ratio(const_ret, n_trials=10)
        assert isinstance(dsr_const, float) and 0.0 <= dsr_const <= 1.0

        # Heavily skewed series
        skew_ret = pd.Series([0.02] * 290 + [-0.50] * 10)
        dsr_skew = compute_deflated_sharpe_ratio(skew_ret, n_trials=10)
        assert isinstance(dsr_skew, float) and 0.0 <= dsr_skew <= 1.0

    def test_expected_max_sharpe_ratio_raises_on_nonpositive_variance(self):
        """compute_expected_max_sharpe_ratio must fail closed with ValueError when var_sr <= 0."""
        import pytest
        with pytest.raises(ValueError, match="var_sr must be positive"):
            compute_expected_max_sharpe_ratio(n_trials=10, var_sr=0.0)
        with pytest.raises(ValueError, match="var_sr must be positive"):
            compute_expected_max_sharpe_ratio(n_trials=10, var_sr=-0.5)


class TestFactorReturnAttribution:
    """Verifies institutional factor decomposition into Market Beta, Sector, and Alpha."""

    def test_factor_attribution_decomposition(self):
        """Decomposes portfolio returns into beta return and alpha return."""
        np.random.seed(42)
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        benchmark_ret = pd.Series(np.random.normal(0.0005, 0.01, size=100), index=dates)

        # Portfolio has beta=1.2 to benchmark plus steady positive alpha of 10 bps/day
        alpha_true = 0.0010
        port_ret = 1.2 * benchmark_ret + alpha_true + np.random.normal(0.0, 0.002, size=100)
        port_ret = pd.Series(port_ret, index=dates)

        attribution = compute_factor_return_attribution(port_ret, benchmark_ret)

        assert "beta" in attribution
        assert "alpha_annualized" in attribution
        assert "information_ratio" in attribution
        assert "total_return" in attribution
        assert "benchmark_return" in attribution

        # Estimated beta should be close to 1.2
        assert np.isclose(attribution["beta"], 1.2, atol=0.15)
        # Alpha should be positive and substantial
        assert attribution["alpha_annualized"] > 0.10
        assert attribution["information_ratio"] > 0.5

    def test_factor_attribution_short_series_fallback_schema_symmetry(self):
        """Short or empty series must return full symmetric schema including tracking_error_annualized."""
        short_port = pd.Series([0.01, -0.02])
        short_bench = pd.Series([0.005, -0.01])
        res = compute_factor_return_attribution(short_port, short_bench)

        expected_keys = {
            "beta",
            "alpha_annualized",
            "tracking_error_annualized",
            "information_ratio",
            "total_return",
            "benchmark_return",
        }
        assert set(res.keys()) == expected_keys
        assert res["tracking_error_annualized"] == 0.0
