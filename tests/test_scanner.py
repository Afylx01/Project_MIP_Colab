"""
MIP Android — Scanner Import & Configuration Tests
Validates scanner module imports and frozen strategy configuration.
Does NOT run actual scans (requires universe.db).
"""

import unittest
import sys
import hashlib
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


CANONICAL_FINGERPRINT = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"

CANONICAL_STRATEGY_PARAMETERS = {
    "ema_regime_span": 20,
    "ema_rs_span": 200,
    "ema_trend_span": 200,
    "exit_buffer_rank": 40,
    "max_per_sector": 2,
    "momentum_lookback_bars": 252,
    "retrace_threshold": 0.80,
    "top_n_candidates": 20,
    "volatility_floor": 0.05,
}


class TestScannerImport(unittest.TestCase):
    """Verify scanner module and its dependencies are importable."""

    def test_import_scanner(self):
        from core.scanner import PydroidScanner
        self.assertIsNotNone(PydroidScanner)

    def test_import_config(self):
        from core.config import MIPScannerConfig
        self.assertIsNotNone(MIPScannerConfig)

    def test_import_reason_codes(self):
        from core.reason_codes import ScannerReasonCode
        self.assertIsNotNone(ScannerReasonCode)

    def test_import_validation(self):
        from core.validation import ScannerDataValidator
        self.assertIsNotNone(ScannerDataValidator)

    def test_import_identity(self):
        from core.identity import SecurityIdentityManager
        self.assertIsNotNone(SecurityIdentityManager)

    def test_import_anomaly(self):
        from core.anomaly import ScannerAnomalyDetector
        self.assertIsNotNone(ScannerAnomalyDetector)

    def test_import_health(self):
        from core.health import ScannerHealthMonitor
        self.assertIsNotNone(ScannerHealthMonitor)

    def test_import_portfolio(self):
        from core.portfolio import PortfolioManager
        self.assertIsNotNone(PortfolioManager)

    def test_import_backtest(self):
        from core.backtest import LightweightBacktester
        self.assertIsNotNone(LightweightBacktester)

    def test_import_breadth(self):
        from core.breadth import MarketBreadthEngine
        self.assertIsNotNone(MarketBreadthEngine)

    def test_import_sector_rotation(self):
        from core.sector_rotation import SectorRotationEngine
        self.assertIsNotNone(SectorRotationEngine)

    def test_import_excel_generator(self):
        from core.excel_generator import InstitutionalExcelGenerator
        self.assertIsNotNone(InstitutionalExcelGenerator)

    def test_import_visuals(self):
        from core.visuals import generate_matplotlib_dashboard
        self.assertIsNotNone(generate_matplotlib_dashboard)

    def test_import_telegram(self):
        from core.telegram_sender import PydroidTelegramSender
        self.assertIsNotNone(PydroidTelegramSender)


class TestStrategyFingerprint(unittest.TestCase):
    """Verify frozen strategy parameters produce the canonical fingerprint."""

    def test_fingerprint_matches(self):
        serialized = json.dumps(CANONICAL_STRATEGY_PARAMETERS, sort_keys=True)
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.assertEqual(fp, CANONICAL_FINGERPRINT,
                         f"Strategy fingerprint mismatch!\n"
                         f"  Expected: {CANONICAL_FINGERPRINT}\n"
                         f"  Got:      {fp}")

    def test_config_module_parameters(self):
        """Verify config.py contains the correct strategy parameters."""
        from core.config import MIPScannerConfig
        cfg = MIPScannerConfig()
        # Check key parameters match canonical values
        self.assertEqual(cfg.retrace_threshold, 0.80)
        self.assertEqual(cfg.momentum_lookback_bars, 252)
        self.assertEqual(cfg.ema_trend_span, 200)
        self.assertEqual(cfg.ema_rs_span, 200)
        self.assertEqual(cfg.ema_regime_span, 20)
        self.assertEqual(cfg.top_n_candidates, 20)
        self.assertEqual(cfg.max_per_sector, 2)
        self.assertAlmostEqual(cfg.volatility_floor, 0.05)
        self.assertEqual(cfg.exit_buffer_rank, 40)


class TestNoHardcodedPaths(unittest.TestCase):
    """Verify no hardcoded old-project paths remain in critical modules."""

    CRITICAL_MODULES = [
        "data_engine.py", "scanner.py", "portfolio.py", "backtest.py",
        "excel_generator.py", "visuals.py", "auto_fetch.py", "settings.py",
    ]

    def test_no_old_project_references(self):
        for mod in self.CRITICAL_MODULES:
            path = PROJECT_ROOT / "core" / mod
            if path.exists():
                source = path.read_text(encoding="utf-8")
                # Check for hardcoded old project paths in non-comment lines
                for line_no, line in enumerate(source.split("\n"), 1):
                    stripped = line.strip()
                    if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                        continue
                    if "Project_MIP_Pydroid3" in line and "import" not in line.lower():
                        # Allow in docstrings/comments but not in executable code
                        if not (stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'")):
                            self.fail(f"{mod}:{line_no} contains hardcoded old project reference: {stripped}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
