"""
tests/test_ablation_feature_statistics.py
Tests verifying empirical return series handling, fail-closed statistics,
and stale trade log protection in SystematicAblationAuditor.
"""

import unittest
from unittest.mock import MagicMock
from pathlib import Path
import tempfile
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from scripts.audit_feature_ablation import SystematicAblationAuditor


class TestAblationFeatureStatistics(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.tmp_dir.name)
        (self.base_dir / "reports" / "ablation_audit").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_ablation_statistics_fail_closed_when_monthly_returns_missing(self):
        """When bt.run returns no monthly_returns, psr and dsr must be None and statistics_unavailable must be True."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)
        mock_result = {
            "cagr_pct": 25.0,
            "sharpe_ratio": 1.2,
            "sortino_ratio": 1.5,
            "calmar_ratio": 0.9,
            "max_drawdown_pct": -20.0,
            "daily_max_drawdown_pct": -25.0,
            "final_equity": 2000000.0,
            "total_trades": 50,
            "win_rate_pct": 55.0,
            "years": 5.0,
            # 'monthly_returns' deliberately omitted
        }
        auditor.bt.run = MagicMock(return_value=mock_result)

        rows = auditor.run_ablation_campaign()
        row0 = rows[0]
        self.assertIsNone(row0["psr"])
        self.assertIsNone(row0["dsr"])
        self.assertTrue(row0["statistics_unavailable"])

    def test_ablation_statistics_use_empirical_monthly_returns(self):
        """When bt.run returns empirical monthly returns, psr and dsr must be valid floats in [0, 1] and not both 1.0."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)
        np.random.seed(123)
        mock_returns = list(np.random.normal(loc=0.015, scale=0.04, size=60))
        mock_result = {
            "cagr_pct": 22.0,
            "sharpe_ratio": 1.1,
            "sortino_ratio": 1.4,
            "calmar_ratio": 0.85,
            "max_drawdown_pct": -18.0,
            "daily_max_drawdown_pct": -22.0,
            "final_equity": 2500000.0,
            "total_trades": 80,
            "win_rate_pct": 52.0,
            "years": 5.0,
            "monthly_returns": mock_returns,
        }
        auditor.bt.run = MagicMock(return_value=mock_result)

        rows = auditor.run_ablation_campaign()
        row0 = rows[0]
        self.assertFalse(row0["statistics_unavailable"])
        self.assertIsInstance(row0["psr"], float)
        self.assertIsInstance(row0["dsr"], float)
        self.assertTrue(0.0 <= row0["psr"] <= 1.0)
        self.assertTrue(0.0 <= row0["dsr"] <= 1.0)
        self.assertFalse(row0["psr"] == 1.0 and row0["dsr"] == 1.0)

    def test_ablation_profit_factor_not_contaminated_by_stale_trade_log(self):
        """When bt.run succeeds without emitting trade_log_path, pre-existing trade_log.csv must not be used."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)

        # Pre-write a stale trade_log.csv with high net_pnl
        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        stale_trade_log = reports_dir / "trade_log.csv"
        stale_df = pd.DataFrame({
            "net_pnl": [50000.0, 30000.0, -1000.0]
        })
        stale_df.to_csv(stale_trade_log, index=False)

        # Mock bt.run returning successful dict WITHOUT trade_log_path and with total_trades=0
        mock_result = {
            "cagr_pct": 20.0,
            "sharpe_ratio": 1.0,
            "sortino_ratio": 1.2,
            "calmar_ratio": 0.8,
            "max_drawdown_pct": -20.0,
            "daily_max_drawdown_pct": -22.0,
            "final_equity": 2000000.0,
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "years": 5.0,
            "monthly_returns": [0.015] * 60,
            # 'trade_log_path' omitted!
        }
        auditor.bt.run = MagicMock(return_value=mock_result)

        rows = auditor.run_ablation_campaign()
        row0 = rows[0]
        self.assertIn(row0["profit_factor"], (None, 0.0))
        self.assertNotIn(row0["profit_factor"], (50.0, 99.99, 80.0))

    def test_psr_dsr_receive_excess_monthly_returns(self):
        """DSR and PSR must receive excess monthly returns over the risk-free rate (6.5% / 12), not raw returns."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)
        raw_returns = [0.02] * 60
        expected_excess = np.array(raw_returns, dtype=float) - (0.065 / 12.0)

        mock_result = {
            "cagr_pct": 24.0,
            "sharpe_ratio": 1.3,
            "sortino_ratio": 1.6,
            "calmar_ratio": 1.0,
            "max_drawdown_pct": -15.0,
            "daily_max_drawdown_pct": -18.0,
            "final_equity": 3000000.0,
            "total_trades": 70,
            "win_rate_pct": 55.0,
            "years": 5.0,
            "monthly_returns": raw_returns,
        }
        auditor.bt.run = MagicMock(return_value=mock_result)

        from unittest.mock import patch
        with patch("scripts.audit_feature_ablation.compute_deflated_sharpe_ratio", return_value=0.85) as spy_dsr, \
             patch("scripts.audit_feature_ablation.compute_probabilistic_sharpe_ratio", return_value=0.95) as spy_psr:
            auditor.run_ablation_campaign()

            self.assertTrue(spy_dsr.called, "compute_deflated_sharpe_ratio must be called")
            self.assertTrue(spy_psr.called, "compute_probabilistic_sharpe_ratio must be called")

            dsr_arg = spy_dsr.call_args[0][0]
            psr_arg = spy_psr.call_args[0][0]

            np.testing.assert_allclose(dsr_arg, expected_excess, rtol=1e-6, atol=1e-6)
            np.testing.assert_allclose(psr_arg, expected_excess, rtol=1e-6, atol=1e-6)

    def test_classification_requires_bonferroni_and_dsr(self):
        """Under Uniform Policy A, a feature with high DSR and high delta Sharpe is NOT_STATISTICALLY_SIGNIFICANT if p_bonf >= 0.05."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)

        # High DSR (0.99) and delta_sharpe (+0.50), but p_bonf = 0.90 (>= 0.05)
        verdict = auditor._classify_feature(
            exp_id="RUN_1_TEST",
            delta_cagr=5.0,
            delta_sharpe=0.50,
            delta_max_dd=1.0,
            dsr=0.99,
            p_value_bonferroni=0.90,
            p_bonf=0.90,
            statistics_unavailable=False,
        )
        self.assertEqual(verdict, "NOT_STATISTICALLY_SIGNIFICANT")

        # When p_bonf < 0.05 and dsr >= 0.50 with +0.50 Sharpe -> PROVEN_PROFITABLE
        verdict_pass = auditor._classify_feature(
            exp_id="RUN_1_TEST",
            delta_cagr=5.0,
            delta_sharpe=0.50,
            delta_max_dd=1.0,
            dsr=0.99,
            p_value_bonferroni=0.01,
            p_bonf=0.01,
            statistics_unavailable=False,
        )
        self.assertEqual(verdict_pass, "PROVEN_PROFITABLE")

    def test_ablation_preserves_shared_trade_log(self):
        """F-06: Pre-existing trade_log.csv must remain intact and must not be deleted on backtest failure."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)

        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        trade_log = reports_dir / "trade_log.csv"
        trade_log.write_text("symbol,net_pnl\nAAA,1234.5\n")

        auditor.bt.run = MagicMock(side_effect=RuntimeError("Engine failure"))
        rows = auditor.run_ablation_campaign()

        self.assertTrue(trade_log.exists(), "trade_log.csv must not be unlinked on failure")
        self.assertEqual(trade_log.read_text(), "symbol,net_pnl\nAAA,1234.5\n")

    def test_proven_label_requires_available_statistics(self):
        """Mock a run with monthly_returns=None and delta_sharpe >= 0.10; assert classification is not PROVEN_PROFITABLE."""
        auditor = SystematicAblationAuditor(base_dir=self.base_dir)

        call_count = 0
        def mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Baseline
                return {
                    "cagr_pct": 20.0,
                    "sharpe_ratio": 1.0,
                    "sortino_ratio": 1.3,
                    "calmar_ratio": 0.8,
                    "max_drawdown_pct": -25.0,
                    "daily_max_drawdown_pct": -28.0,
                    "final_equity": 2000000.0,
                    "total_trades": 60,
                    "win_rate_pct": 50.0,
                    "years": 5.0,
                    "monthly_returns": None,
                }
            else:
                # Feature with +0.50 Sharpe improvement
                return {
                    "cagr_pct": 28.0,
                    "sharpe_ratio": 1.5,
                    "sortino_ratio": 2.0,
                    "calmar_ratio": 1.4,
                    "max_drawdown_pct": -20.0,
                    "daily_max_drawdown_pct": -22.0,
                    "final_equity": 3500000.0,
                    "total_trades": 65,
                    "win_rate_pct": 55.0,
                    "years": 5.0,
                    "monthly_returns": None,
                }

        auditor.bt.run = MagicMock(side_effect=mock_run)
        rows = auditor.run_ablation_campaign()
        row1 = rows[1]
        self.assertNotEqual(row1["classification"], "PROVEN_PROFITABLE")
        self.assertEqual(row1["classification"], "NOT_STATISTICALLY_SIGNIFICANT")
        self.assertTrue(row1["statistics_unavailable"])

        # Generate markdown scorecard
        md = auditor.generate_scorecard_markdown(rows)
        self.assertIn("N/A (statistics unavailable)", md)
        self.assertIn("**Statistics:** UNAVAILABLE (insufficient sample)", md)
