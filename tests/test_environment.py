"""
MIP Android — Environment Validation Tests
Verifies Python version, required packages, and project structure.
"""

import sys
import os
import unittest
from pathlib import Path


# Project root: tests/ -> MIP_Android/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestPythonEnvironment(unittest.TestCase):
    """Verify Python version and critical built-in modules."""

    def test_python_version_minimum(self):
        """Python 3.11+ required for match statements and performance."""
        self.assertGreaterEqual(sys.version_info[:2], (3, 11),
                                f"Python 3.11+ required, got {sys.version}")

    def test_sqlite3_available(self):
        """SQLite3 is the data backbone — must be available."""
        import sqlite3
        self.assertIsNotNone(sqlite3.sqlite_version)

    def test_pathlib_available(self):
        """pathlib is used throughout for path resolution."""
        from pathlib import Path
        self.assertIsNotNone(Path)


class TestRequiredPackages(unittest.TestCase):
    """Verify all required third-party packages are importable."""

    def test_pandas(self):
        import pandas
        self.assertIsNotNone(pandas.__version__)

    def test_numpy(self):
        import numpy
        self.assertIsNotNone(numpy.__version__)

    def test_scipy(self):
        import scipy
        self.assertIsNotNone(scipy.__version__)

    def test_matplotlib(self):
        import matplotlib
        self.assertIsNotNone(matplotlib.__version__)

    def test_openpyxl(self):
        import openpyxl
        self.assertIsNotNone(openpyxl.__version__)

    def test_requests(self):
        import requests
        self.assertIsNotNone(requests.__version__)


class TestOptionalPackages(unittest.TestCase):
    """Check optional packages — failures are warnings, not errors."""

    def test_plotly_optional(self):
        try:
            import plotly
            self.assertIsNotNone(plotly.__version__)
        except ImportError:
            self.skipTest("plotly not available (optional)")

    def test_curl_cffi_optional(self):
        try:
            from curl_cffi import requests
            self.assertIsNotNone(requests)
        except ImportError:
            self.skipTest("curl_cffi not available (optional)")

    def test_numba_optional(self):
        try:
            import numba
            self.assertIsNotNone(numba.__version__)
        except ImportError:
            self.skipTest("numba not available (optional)")


class TestProjectStructure(unittest.TestCase):
    """Verify the expected project directory structure exists."""

    def test_core_directory(self):
        self.assertTrue((PROJECT_ROOT / "core").is_dir())

    def test_data_directory(self):
        self.assertTrue((PROJECT_ROOT / "data").is_dir())

    def test_reports_directory(self):
        self.assertTrue((PROJECT_ROOT / "reports").is_dir())

    def test_tests_directory(self):
        self.assertTrue((PROJECT_ROOT / "tests").is_dir())

    def test_main_py_exists(self):
        self.assertTrue((PROJECT_ROOT / "main.py").is_file())

    def test_core_init_exists(self):
        self.assertTrue((PROJECT_ROOT / "core" / "__init__.py").is_file())

    def test_gitignore_exists(self):
        self.assertTrue((PROJECT_ROOT / ".gitignore").is_file())

    def test_env_example_exists(self):
        self.assertTrue((PROJECT_ROOT / ".env.example").is_file())

    def test_no_env_file_committed(self):
        """Ensure no .env file with real credentials exists in VCS."""
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            # It's ok to exist locally, but verify .gitignore covers it
            gitignore = (PROJECT_ROOT / ".gitignore").read_text()
            self.assertIn(".env", gitignore,
                          ".env exists but is not in .gitignore!")

    def test_no_research_directory(self):
        """Research artifacts must NOT exist in the Android project."""
        self.assertFalse((PROJECT_ROOT / "research").is_dir(),
                         "research/ directory should not exist in Android project")

    def test_no_paper_trading_directory(self):
        self.assertFalse((PROJECT_ROOT / "paper_trading").is_dir(),
                         "paper_trading/ directory should not exist in Android project")


class TestDataFiles(unittest.TestCase):
    """Verify bundled runtime data files."""

    def test_benchmark_csv(self):
        self.assertTrue((PROJECT_ROOT / "data" / "benchmark_nifty500.csv").is_file())

    def test_sector_map(self):
        self.assertTrue((PROJECT_ROOT / "data" / "symbol_sector_map.json").is_file())

    def test_trading_calendar(self):
        self.assertTrue((PROJECT_ROOT / "data" / "trading_calendar.txt").is_file())

    def test_etf_list(self):
        self.assertTrue((PROJECT_ROOT / "data" / "eq_etfseclist.csv").is_file())

    def test_settings_example(self):
        self.assertTrue((PROJECT_ROOT / "data" / "investing_settings.example.json").is_file())

    def test_settings_example_valid_json(self):
        import json
        path = PROJECT_ROOT / "data" / "investing_settings.example.json"
        data = json.loads(path.read_text())
        self.assertIn("capital", data)
        self.assertIn("top_n", data)
        self.assertIn("sizing_mode", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
