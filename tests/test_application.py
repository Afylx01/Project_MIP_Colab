"""
MIP Android — Application Integration Tests
Validates that the main application entry point and top-level imports work.
Does NOT launch the interactive TUI.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestMainImports(unittest.TestCase):
    """Verify all top-level imports in main.py are resolvable."""

    def test_core_data_engine_imports(self):
        from core.data_engine import (
            get_base_dir, get_db_path, get_connection
        )
        self.assertTrue(callable(get_base_dir))

    def test_core_scanner_imports(self):
        from core.scanner import PydroidScanner, format_screener_tearsheet
        self.assertIsNotNone(PydroidScanner)
        self.assertTrue(callable(format_screener_tearsheet))

    def test_core_breadth_imports(self):
        from core.breadth import MarketBreadthEngine
        self.assertIsNotNone(MarketBreadthEngine)

    def test_core_sector_rotation_imports(self):
        from core.sector_rotation import SectorRotationEngine
        self.assertIsNotNone(SectorRotationEngine)

    def test_core_visuals_imports(self):
        from core.visuals import generate_matplotlib_dashboard, generate_plotly_tearsheet
        self.assertTrue(callable(generate_matplotlib_dashboard))

    def test_core_telegram_imports(self):
        from core.telegram_sender import PydroidTelegramSender, format_telegram_alert
        self.assertIsNotNone(PydroidTelegramSender)

    def test_core_backtest_imports(self):
        from core.backtest import LightweightBacktester
        self.assertIsNotNone(LightweightBacktester)

    def test_core_portfolio_imports(self):
        from core.portfolio import PortfolioManager
        self.assertIsNotNone(PortfolioManager)

    def test_core_settings_imports(self):
        from core.settings import load_investing_settings
        self.assertTrue(callable(load_investing_settings))

    def test_core_auto_fetch_imports(self):
        from core.auto_fetch import PydroidAutoFetch
        self.assertIsNotNone(PydroidAutoFetch)

    def test_core_etf_engine_imports(self):
        from core.etf_engine import ETFMomentumEngine
        self.assertIsNotNone(ETFMomentumEngine)

    def test_core_delivery_imports(self):
        from core.delivery import NSEDeliveryManager
        self.assertIsNotNone(NSEDeliveryManager)

    def test_core_sync_sectors_imports(self):
        from core.sync_sectors import sync_nse_sectors
        self.assertTrue(callable(sync_nse_sectors))


class TestNoImportErrors(unittest.TestCase):
    """Verify no import chain produces an error."""

    def test_all_core_modules_importable(self):
        """Import every module in core/ to catch broken import chains."""
        import importlib
        core_dir = PROJECT_ROOT / "core"
        failures = []
        for py_file in sorted(core_dir.glob("*.py")):
            if py_file.name == "__init__.py":
                continue
            module_name = f"core.{py_file.stem}"
            try:
                importlib.import_module(module_name)
            except Exception as e:
                failures.append(f"{module_name}: {type(e).__name__}: {e}")

        if failures:
            self.fail(
                f"Import failures in {len(failures)} module(s):\n"
                + "\n".join(f"  - {f}" for f in failures)
            )


class TestMainPyNoAbsoluteOldImports(unittest.TestCase):
    """Verify main.py has no remaining references to old package."""

    def test_no_pydroid_core_references(self):
        main_source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertNotIn("pydroid_core", main_source,
                         "main.py still contains 'pydroid_core' references")


if __name__ == "__main__":
    unittest.main(verbosity=2)
