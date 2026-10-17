"""
tests/test_colab_package.py - Unit & Contract Tests for the Modular colab Package
Verifies that colab.environment, colab.screener, and colab.dashboard function cleanly.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestColabPackage(unittest.TestCase):
    """Test suite for the modular colab package."""

    def test_colab_package_imports(self):
        """Verify that all public entry points in colab package import cleanly."""
        import colab
        self.assertTrue(hasattr(colab, "setup_colab_environment"))
        self.assertTrue(hasattr(colab, "run_screener_view"))
        self.assertTrue(hasattr(colab, "render_backtest_dashboard"))

    def test_environment_helpers(self):
        """Verify environment helper functions (is_in_colab, is_gzipped_file)."""
        from colab.environment import is_in_colab, is_gzipped_file
        # When running locally / in tests, is_in_colab returns a boolean
        res = is_in_colab()
        self.assertIsInstance(res, bool)

        # Check non-existent file
        fake_path = Path("/tmp/non_existent_probe_file.gz")
        self.assertFalse(is_gzipped_file(fake_path))

    def test_setup_colab_environment_local(self):
        """Verify setup_colab_environment runs in non-interactive local mode."""
        from colab.environment import setup_colab_environment
        report = setup_colab_environment(verbose=False, mount_drive=False, download_if_missing=False)
        self.assertIsInstance(report, dict)
        self.assertIn("in_colab", report)
        self.assertIn("db_exists", report)
        self.assertIn("db_path", report)

    def test_screener_view_signature(self):
        """Verify run_screener_view has correct signature and parameter defaults."""
        import inspect
        from colab.screener import run_screener_view
        sig = inspect.signature(run_screener_view)
        params = sig.parameters
        self.assertIn("universe", params)
        self.assertIn("benchmark", params)
        self.assertIn("top_n", params)
        self.assertIn("use_vol_targeting", params)
        self.assertIn("use_delivery_veto", params)
        self.assertIn("use_residual_momentum", params)
        self.assertEqual(params["universe"].default, "NIFTY750")
        self.assertEqual(params["benchmark"].default, "NIFTY500")

    def test_dashboard_renderer_callable(self):
        """Verify render_backtest_dashboard is callable and runs without uncaught exceptions."""
        from colab.dashboard import render_backtest_dashboard, get_runner_instance
        runner = get_runner_instance()
        self.assertIsNotNone(runner)

        # In headless environment without ipywidgets, returns None gracefully
        res = render_backtest_dashboard()
        # Either returns widgets.VBox (in notebook) or None (headless without widgets)
        self.assertTrue(res is None or hasattr(res, "children"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
