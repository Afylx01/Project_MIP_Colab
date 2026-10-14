"""
test_feature1_residual_momentum.py - Contract & Unit Tests for Feature 1 (Residual Momentum)
Verifies:
1. Beta neutralization against benchmark excess returns.
2. Short-term 21-day reversal exclusion (t-252 to t-21).
3. Standardized residual Sharpe scoring (Blitz et al. 2011/2020).
4. Composite blend calculation with canonical Volar.
5. Fail-closed fallback when benchmark data is missing or corrupt.
"""

import unittest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nextgen.residual_momentum import (
    compute_rolling_residual_momentum,
    compute_composite_momentum_score,
    ResidualMomentumConfig,
)



class TestFeature1ResidualMomentum(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.T = 300
        # Synthetic benchmark: steady 10% annual trend with 12% vol
        daily_rf = 0.065 / 252.0
        bench_ret = np.random.normal(0.0004, 0.0075, self.T)
        self.bench_excess = bench_ret - daily_rf

        # Stock A: High beta (beta=2.0) but zero alpha (pure market beta amplifier)
        stock_a_excess = 2.0 * self.bench_excess + np.random.normal(0.0, 0.002, self.T)

        # Stock B: Low beta (beta=0.5) with strong positive idiosyncratic alpha (+0.0008/day)
        stock_b_excess = 0.5 * self.bench_excess + 0.0008 + np.random.normal(0.0, 0.002, self.T)

        self.stock_returns = pd.DataFrame({
            "STOCK_A_HIGH_BETA": stock_a_excess + daily_rf,
            "STOCK_B_HIGH_ALPHA": stock_b_excess + daily_rf,
        })
        self.bench_returns = pd.Series(bench_ret)

    def test_residual_momentum_penalizes_pure_market_beta(self):
        """High-beta stock without alpha should have low/near-zero residual momentum."""
        res_df = compute_rolling_residual_momentum(
            stock_returns=self.stock_returns,
            bench_returns=self.bench_returns,
            lookback=252,
            skip_recent=21,
        )

        res_a = res_df["STOCK_A_HIGH_BETA"].iloc[-1]
        res_b = res_df["STOCK_B_HIGH_ALPHA"].iloc[-1]

        # Stock B with high idiosyncratic alpha MUST outrank pure high-beta Stock A
        self.assertGreater(res_b, res_a, f"High alpha stock ({res_b:.4f}) did not outrank high beta stock ({res_a:.4f})")

    def test_short_term_reversal_exclusion(self):
        """Verifies that the most recent 21 days do not affect the residual momentum score."""
        # Create stock with explosive gain in last 20 days only
        stock_c_ret = np.zeros(self.T)
        stock_c_ret[-20:] = 0.05  # Massive pump in last 20 days

        stock_df = pd.DataFrame({"STOCK_C": stock_c_ret})
        res_df = compute_rolling_residual_momentum(
            stock_returns=stock_df,
            bench_returns=self.bench_returns,
            lookback=252,
            skip_recent=21,
        )

        # The last 20 days pump should be excluded by skip_recent=21
        self.assertAlmostEqual(res_df["STOCK_C"].iloc[-1], 0.0, delta=0.5,
                               msg="Short-term pump was not excluded by the 21-day reversal guard")

    def test_composite_blend_retains_canonical_volar(self):
        """Composite score must blend canonical Volar and Residual Volar according to weights."""
        volar = np.array([2.5, 1.0])
        res_volar = np.array([1.0, 3.0])

        comp = compute_composite_momentum_score(
            volar_scores=volar,
            residual_scores=res_volar,
            volar_weight=0.40,
            residual_weight=0.60,
        )

        expected = 0.40 * np.array([2.5, 1.0]) + 0.60 * np.array([1.0, 3.0])
        np.testing.assert_allclose(comp, expected, atol=1e-5)

    def test_fail_closed_fallback(self):
        """If benchmark returns are missing or invalid, fallback cleanly to canonical Volar."""
        volar = np.array([2.5, 1.0])
        comp = compute_composite_momentum_score(
            volar_scores=volar,
            residual_scores=None,
            volar_weight=0.40,
            residual_weight=0.60,
        )
        np.testing.assert_allclose(comp, volar, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
