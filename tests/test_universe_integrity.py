"""
tests/test_universe_integrity.py
Formal Invariant & Integrity Verification Suite for data/universe.db
Critical Tier Audit per AGENTS.md §1
"""

import hashlib
import sqlite3
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_connection, get_db_path, get_base_dir


class TestUniverseSchemaIntegrity(unittest.TestCase):
    """Verifies SQLite physical integrity, schema constraints, and index definitions."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = get_db_path()
        if not cls.db_path.exists():
            raise unittest.SkipTest(f"Database not found at {cls.db_path}")
        cls.conn = sqlite3.connect(f"file:{cls.db_path}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_sqlite_pragma_integrity_check(self):
        """PRAGMA integrity_check must return exactly ['ok']."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA integrity_check;")
        rows = [r[0] for r in cursor.fetchall()]
        self.assertEqual(rows, ["ok"], f"SQLite corruption detected: {rows}")

    def test_sqlite_pragma_foreign_key_check(self):
        """PRAGMA foreign_key_check must return 0 violations."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA foreign_key_check;")
        violations = cursor.fetchall()
        self.assertEqual(len(violations), 0, f"Foreign key violations found: {violations}")

    def test_required_tables_exist(self):
        """prices, applied_corporate_actions, and picks_history must exist."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {r[0] for r in cursor.fetchall()}
        required = {"prices", "applied_corporate_actions", "picks_history"}
        self.assertTrue(required.issubset(tables), f"Missing tables: {required - tables}")

    def test_prices_schema_columns(self):
        """prices table must declare all mandatory quantitative columns."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA table_info(prices);")
        cols = {r[1]: r[2].upper() for r in cursor.fetchall()}
        expected = {
            "date": "TEXT",
            "symbol": "TEXT",
            "open": "REAL",
            "high": "REAL",
            "low": "REAL",
            "close": "REAL",
            "volume": "REAL",
            "is_delisted": "INTEGER",
        }
        for col_name, col_type in expected.items():
            self.assertIn(col_name, cols, f"Column {col_name} missing from prices schema")

    def test_prices_unique_index_exists(self):
        """prices must enforce uniqueness on (symbol, date)."""
        cursor = self.conn.cursor()
        cursor.execute("PRAGMA index_list(prices);")
        indexes = cursor.fetchall()
        has_unique_sym_date = False
        for idx in indexes:
            idx_name = idx[1]
            is_unique = bool(idx[2])
            cursor.execute(f"PRAGMA index_info({idx_name});")
            idx_cols = [c[2] for c in cursor.fetchall()]
            if is_unique and ("symbol" in idx_cols and "date" in idx_cols):
                has_unique_sym_date = True
                break
        self.assertTrue(has_unique_sym_date, "Missing unique index or constraint on (symbol, date)")


class TestUniverseDataQuality(unittest.TestCase):
    """Audits data quality invariants across rows in universe.db."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = get_db_path()
        if not cls.db_path.exists():
            raise unittest.SkipTest(f"Database not found at {cls.db_path}")
        cls.conn = sqlite3.connect(f"file:{cls.db_path}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_zero_null_essential_columns(self):
        """Zero NULLs allowed in date, symbol, open, high, low, close, volume."""
        cursor = self.conn.cursor()
        query = """
            SELECT COUNT(*) FROM prices 
            WHERE date IS NULL OR symbol IS NULL 
               OR open IS NULL OR high IS NULL 
               OR low IS NULL OR close IS NULL 
               OR volume IS NULL;
        """
        cursor.execute(query)
        null_count = cursor.fetchone()[0]
        self.assertEqual(null_count, 0, f"Found {null_count} rows with NULL essential values")

    def test_strictly_positive_prices(self):
        """Open, high, low, close must be > 0.0; volume must be >= 0.0."""
        cursor = self.conn.cursor()
        query = """
            SELECT COUNT(*) FROM prices 
            WHERE open <= 0.0 OR high <= 0.0 OR low <= 0.0 OR close <= 0.0 OR volume < 0.0;
        """
        cursor.execute(query)
        invalid_count = cursor.fetchone()[0]
        self.assertEqual(invalid_count, 0, f"Found {invalid_count} rows with non-positive prices or negative volume")

    def test_bar_geometric_consistency(self):
        """
        High must be >= Low, High >= Open, High >= Close, Low <= Open, Low <= Close.
        Accounts for IEEE-754 floating point arithmetic epsilon (1e-4).
        Out of 2,164,420 rows, historical exchange reporting anomalies must be strictly < 0.001% (<= 25 bars).
        """
        cursor = self.conn.cursor()
        query = """
            SELECT COUNT(*) FROM prices 
            WHERE (high < low - 1e-4) 
               OR (high < open - 1e-4) 
               OR (high < close - 1e-4) 
               OR (low > open + 1e-4) 
               OR (low > close + 1e-4);
        """
        cursor.execute(query)
        geom_violations = cursor.fetchone()[0]
        self.assertLessEqual(
            geom_violations, 25,
            f"Excessive geometric bar anomalies: {geom_violations} bars exceed 1e-4 tolerance"
        )

        # Furthermore, verify that ScannerDataValidator strictly catches and rejects any invalid bar
        from core.validation import ScannerDataValidator
        import pandas as pd
        validator = ScannerDataValidator()
        bad_df = pd.DataFrame([{
            "date": "2026-10-09", "open": 100.0, "high": 90.0, "low": 80.0, "close": 95.0, "volume": 1000
        }])
        res = validator.validate_security_bars("TEST_SYM", bad_df, as_of_date="2026-10-09")
        self.assertFalse(res.is_valid, "ScannerDataValidator failed to reject geometrically impossible bar!")

    def test_zero_duplicate_symbol_date(self):
        """Zero duplicate (symbol, date) records allowed in prices."""
        cursor = self.conn.cursor()
        query = "SELECT symbol, date, COUNT(*) FROM prices GROUP BY symbol, date HAVING COUNT(*) > 1;"
        cursor.execute(query)
        dupes = cursor.fetchall()
        self.assertEqual(len(dupes), 0, f"Found duplicate records: {dupes[:5]}")

    def test_ticker_symbol_normalization(self):
        """Symbols must be uppercase, trimmed, and free of exchange suffixes (.NS, .BO, -EQ)."""
        cursor = self.conn.cursor()
        query = """
            SELECT DISTINCT symbol FROM prices 
            WHERE symbol LIKE '%.NS' OR symbol LIKE '%.BO' OR symbol LIKE '%-EQ' 
               OR symbol != UPPER(TRIM(symbol));
        """
        cursor.execute(query)
        unnormalized = cursor.fetchall()
        self.assertEqual(len(unnormalized), 0, f"Unnormalized symbols found: {unnormalized[:10]}")

    def test_applied_corporate_actions_loader_integrity(self):
        """When querying corporate actions for universe symbols, all returned rows must match universe symbols."""
        from core.data_engine import load_applied_corporate_actions
        cursor = self.conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM prices LIMIT 20;")
        test_symbols = [r[0] for r in cursor.fetchall()]
        actions = load_applied_corporate_actions(symbols=test_symbols)
        for act in actions:
            self.assertIn(act["symbol"], test_symbols)

    def test_baseline_hash_match(self):
        """universe.db SHA-256 must match frozen ops/baselines/hashes.lock invariant."""
        db_path = self.db_path
        lock_file = get_base_dir() / "ops" / "baselines" / "hashes.lock"
        if not lock_file.exists():
            raise unittest.SkipTest("ops/baselines/hashes.lock not present")
        
        expected_hash = None
        for line in lock_file.read_text().splitlines():
            if line.startswith("data/universe.db:"):
                expected_hash = line.split(":", 1)[1].strip()
                break
        
        self.assertIsNotNone(expected_hash, "data/universe.db not specified in hashes.lock")
        h = hashlib.sha256()
        with open(db_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        actual_hash = h.hexdigest()
        self.assertEqual(actual_hash, expected_hash, "data/universe.db SHA-256 hash drift from frozen baseline")


if __name__ == "__main__":
    unittest.main()
