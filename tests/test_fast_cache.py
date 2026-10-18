"""
tests/test_fast_cache.py - Unit Tests for FastDataCache Engine
"""

import unittest
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np

from cache.fast_cache import FastDataCache, HAS_PYARROW


class TestFastDataCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.cache = FastDataCache(cache_dir=self.temp_dir, max_cache_size_mb=10)
        self.db_file = self.temp_dir / "test_db.db"
        self.db_file.write_bytes(b"MOCK_SQLITE_DATA_12345")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_miss_returns_none(self):
        self.assertIsNone(self.cache.get("non_existent_key"))

    def test_roundtrip_dataframe_storage(self):
        df = pd.DataFrame({
            "date": ["2026-10-10", "2026-10-11", "2026-10-12"],
            "symbol": ["RELIANCE", "TCS", "INFY"],
            "close": [2500.5, 3600.0, 1850.25],
            "volume": [100000, 250000, 500000],
        })

        key = self.cache.compute_cache_key(
            db_path=self.db_file,
            table_name="prices",
            start_date="2026-10-10",
            end_date="2026-10-12",
            symbols=["RELIANCE", "TCS", "INFY"],
        )

        # Store in cache
        success = self.cache.store(key, df, description="Test Bars")
        self.assertTrue(success)

        # Retrieve from cache
        retrieved_df = self.cache.get(key)
        self.assertIsNotNone(retrieved_df)
        self.assertEqual(len(retrieved_df), 3)
        self.assertListEqual(list(retrieved_df["symbol"]), ["RELIANCE", "TCS", "INFY"])
        np.testing.assert_allclose(retrieved_df["close"], df["close"])

    def test_key_changes_on_db_mutation(self):
        key1 = self.cache.compute_cache_key(
            db_path=self.db_file,
            table_name="prices",
            start_date="2026-01-01",
            end_date="2026-10-16",
        )

        # Mutate db file
        self.db_file.write_bytes(b"MOCK_SQLITE_DATA_12345_MODIFIED_EXTRA_BYTES")

        key2 = self.cache.compute_cache_key(
            db_path=self.db_file,
            table_name="prices",
            start_date="2026-01-01",
            end_date="2026-10-16",
        )

        self.assertNotEqual(key1, key2, "Cache key must change when database file changes")

    def test_clear_cache(self):
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        key = self.cache.compute_cache_key(self.db_file, "test", "2026-01-01", "2026-01-02")
        self.cache.store(key, df)

        deleted = self.cache.clear()
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.cache.get(key))


if __name__ == "__main__":
    unittest.main()
