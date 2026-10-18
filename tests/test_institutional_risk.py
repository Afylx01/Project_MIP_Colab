"""
tests/test_institutional_risk.py - Unit Tests for Institutional Risk & Tail Engine
"""

import unittest
import numpy as np
import pandas as pd
from analytics.institutional_risk import calculate_comprehensive_risk_suite


class TestInstitutionalRiskAnalytics(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        # 500 sessions of synthetic returns with positive drift
        self.returns = np.random.normal(loc=0.0008, scale=0.012, size=500)
        self.benchmark_returns = np.random.normal(loc=0.0005, scale=0.010, size=500)
        self.equity_curve = np.cumprod(1.0 + self.returns) * 100_000

    def test_risk_suite_contains_mandatory_institutional_keys(self):
        metrics = calculate_comprehensive_risk_suite(
            returns=self.returns,
            equity_curve=self.equity_curve,
            benchmark_returns=self.benchmark_returns,
            rf_rate=0.065,
        )

        mandatory_keys = [
            "cagr",
            "annualized_volatility",
            "downside_volatility",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "max_drawdown",
            "var_95",
            "var_99",
            "cvar_95",
            "cvar_99",
            "ulcer_index",
            "ulcer_performance_index",
            "burke_ratio",
            "omega_ratio",
            "gain_to_pain_ratio",
            "tail_ratio",
            "skewness",
            "kurtosis",
            "max_drawdown_duration_sessions",
            "tracking_error",
            "information_ratio",
            "beta",
            "alpha_annualized",
            "r_squared",
            "systematic_risk_pct",
            "specific_risk_pct",
        ]

        for k in mandatory_keys:
            self.assertIn(k, metrics, f"Missing expected institutional metric: {k}")

    def test_cvar_strictly_exceeds_or_equals_var(self):
        metrics = calculate_comprehensive_risk_suite(self.returns)
        self.assertGreaterEqual(metrics["cvar_95"], metrics["var_95"])
        self.assertGreaterEqual(metrics["cvar_99"], metrics["var_99"])
        self.assertGreaterEqual(metrics["var_99"], metrics["var_95"])

    def test_ulcer_index_zero_on_monotonic_positive_series(self):
        monotonic_positive = np.full(50, 0.01)
        metrics = calculate_comprehensive_risk_suite(monotonic_positive)
        self.assertEqual(metrics["max_drawdown"], 0.0)
        self.assertEqual(metrics["ulcer_index"], 0.0)

    def test_systematic_plus_specific_risk_sums_to_100(self):
        metrics = calculate_comprehensive_risk_suite(
            returns=self.returns,
            benchmark_returns=self.benchmark_returns,
        )
        total_risk_pct = metrics["systematic_risk_pct"] + metrics["specific_risk_pct"]
        self.assertAlmostEqual(total_risk_pct, 100.0, places=1)


if __name__ == "__main__":
    unittest.main()
