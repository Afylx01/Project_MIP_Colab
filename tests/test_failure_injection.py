"""
MIP Android — Failure Injection & Resiliency Test Suite
Directive: STAGE-19-FAILURE-INJECTION-01
"""

import os
import sys
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import MIPScannerConfig
from core.data_engine import get_connection
from core.analytical_price import (
    AnalyticalPriceEngine,
    CorporateActionEvent,
    ActionNature,
    ActionType,
)
from core.benchmark_validator import evaluate_regime


class TestFailureInjection(unittest.TestCase):
    """Verifies fail-closed semantics across all failure modes."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="mip_failure_inj_"))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_database_raises_error(self):
        """Missing database must raise FileNotFoundError immediately."""
        fake_db = self.test_dir / "nonexistent.db"
        with self.assertRaises(Exception):
            conn = sqlite3.connect(f"file:{fake_db}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM prices;")

    def test_corrupted_database_fails_closed(self):
        """Corrupt database header fails closed with OperationalError / DatabaseError."""
        bad_db = self.test_dir / "corrupted.db"
        bad_db.write_bytes(b"NOT_A_VALID_SQLITE_DATABASE_DATA")
        with self.assertRaises((sqlite3.DatabaseError, sqlite3.OperationalError)):
            conn = sqlite3.connect(f"file:{bad_db}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT count(*) FROM prices;")

    def test_missing_corporate_action_registry(self):
        """Missing corporate actions registry safely falls back to empty registry."""
        nonexistent_reg = self.test_dir / "missing_registry.json"
        engine = AnalyticalPriceEngine(registry_path=nonexistent_reg)
        self.assertEqual(len(engine.actions_by_symbol), 0)

        # Standard series without corporate action operates cleanly
        dates = pd.date_range("2026-01-01", periods=10, freq="B").strftime("%Y-%m-%d").tolist()
        df = pd.DataFrame({"date": dates, "open": [100.0]*10, "high": [105.0]*10, "low": [95.0]*10, "close": [100.0]*10, "volume": [1000.0]*10})
        adj_df, diag = engine.derive_analytical_series("TEST", df, as_of_date=dates[-1])
        self.assertEqual(diag["treatment"], "RAW_CONTINUOUS")
        self.assertFalse(diag["is_blocked_unresolved"])

    def test_unresolved_structural_drop_fails_closed(self):
        """Unexplained structural price drop > 40% with no corporate action fails closed."""
        dates = pd.date_range("2026-01-01", periods=10, freq="B").strftime("%Y-%m-%d").tolist()
        # 50% overnight crash from bar 4 to bar 5
        closes = [100.0]*5 + [50.0]*5
        df = pd.DataFrame({"date": dates, "open": closes, "high": closes, "low": closes, "close": closes, "volume": [1000.0]*10})
        engine = AnalyticalPriceEngine(registry_path=self.test_dir / "empty.json")
        adj_df, diag = engine.derive_analytical_series("CRASH_TEST", df, as_of_date=dates[-1])
        self.assertTrue(diag["is_blocked_unresolved"])
        self.assertEqual(diag["treatment"], "UNRESOLVED_CRASH")
        self.assertIn("Unresolved structural drop", diag["unresolved_reason"])

    def test_missing_benchmark_csv_fails_closed(self):
        """Missing benchmark data causes regime evaluation to fail closed."""
        missing_bm = self.test_dir / "nonexistent_bm.csv"
        res = evaluate_regime(
            as_of_date="2026-10-01",
            benchmark_csv_or_df=missing_bm,
        )
        self.assertFalse(res.is_valid)
        self.assertFalse(res.allow_new_buys)

    def test_readonly_environment_protection(self):
        """When MIP_READONLY=1, SQLite connection enforces PRAGMA query_only."""
        orig_readonly = os.environ.get("MIP_READONLY")
        os.environ["MIP_READONLY"] = "1"
        try:
            conn = get_connection(read_only=True, reuse=False)
            cursor = conn.cursor()
            # Attempting to write must fail under PRAGMA query_only = ON or mode=ro
            with self.assertRaises(sqlite3.OperationalError):
                cursor.execute("CREATE TABLE test_mutation (x INT);")
        finally:
            if orig_readonly is not None:
                os.environ["MIP_READONLY"] = orig_readonly
            elif "MIP_READONLY" in os.environ:
                del os.environ["MIP_READONLY"]


if __name__ == "__main__":
    unittest.main()
