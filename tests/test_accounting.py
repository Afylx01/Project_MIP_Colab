"""
MIP Android — Accounting & Portfolio Tests
Validates portfolio module imports and basic configuration.
Does NOT execute trades or require universe.db.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestPortfolioImport(unittest.TestCase):
    """Verify portfolio module is importable with all key classes."""

    def test_import_portfolio_manager(self):
        from core.portfolio import PortfolioManager
        self.assertIsNotNone(PortfolioManager)

    def test_import_normalize_sector(self):
        from core.portfolio import normalize_sector
        self.assertTrue(callable(normalize_sector))

    def test_normalize_sector_function(self):
        """Basic normalization should work without DB."""
        from core.portfolio import normalize_sector
        # normalize_sector should handle None/empty gracefully
        result = normalize_sector(None)
        self.assertIsNotNone(result)


class TestBacktestImport(unittest.TestCase):
    """Verify backtester is importable."""

    def test_import_backtester(self):
        from core.backtest import LightweightBacktester
        self.assertIsNotNone(LightweightBacktester)


class TestSettingsModule(unittest.TestCase):
    """Verify settings module works with example configuration."""

    def test_import_settings(self):
        from core.settings import load_investing_settings
        self.assertTrue(callable(load_investing_settings))

    def test_example_settings_loadable(self):
        """The example settings file should be valid JSON with expected keys."""
        import json
        path = PROJECT_ROOT / "data" / "investing_settings.example.json"
        data = json.loads(path.read_text())
        expected_keys = {
            "capital", "top_n", "max_per_sector", "sizing_mode",
            "risk_per_trade_pct", "atr_stop_multiplier",
            "exit_buffer_multiplier", "cash_buffer_pct",
            "universe_mode", "regime_filter_active", "friction_multiplier",
        }
        self.assertEqual(set(data.keys()), expected_keys,
                         f"Settings keys mismatch. Missing: {expected_keys - set(data.keys())}")


class TestConfigParameters(unittest.TestCase):
    """Verify frozen strategy configuration integrity."""

    def test_config_instantiation(self):
        from core.config import MIPScannerConfig
        cfg = MIPScannerConfig()
        self.assertIsNotNone(cfg)

    def test_frozen_parameters_present(self):
        from core.config import MIPScannerConfig
        cfg = MIPScannerConfig()
        # All canonical parameters must be accessible
        attrs = [
            "retrace_threshold", "momentum_lookback_bars",
            "ema_trend_span", "ema_rs_span", "ema_regime_span",
            "top_n_candidates", "max_per_sector",
            "volatility_floor", "exit_buffer_rank",
        ]
        for attr in attrs:
            self.assertTrue(hasattr(cfg, attr),
                            f"MIPScannerConfig missing attribute: {attr}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
