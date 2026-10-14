"""
MIP Android — Data Engine Tests
Validates data_engine module imports, path resolution, and basic functionality.
Does NOT require universe.db to be present for most tests.
"""

import unittest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestDataEngineImport(unittest.TestCase):
    """Verify data_engine module is importable."""

    def test_import_data_engine(self):
        from core.data_engine import get_base_dir, get_db_path
        self.assertIsNotNone(get_base_dir)
        self.assertIsNotNone(get_db_path)

    def test_import_all_public_functions(self):
        from core.data_engine import (
            get_base_dir,
            get_db_path,
            get_connection,
        )
        self.assertTrue(callable(get_base_dir))
        self.assertTrue(callable(get_db_path))
        self.assertTrue(callable(get_connection))


class TestPathResolution(unittest.TestCase):
    """Verify get_base_dir resolves correctly."""

    def test_base_dir_is_project_root(self):
        from core.data_engine import get_base_dir
        base = get_base_dir()
        # base_dir should resolve to MIP_Android/ (or wherever universe.db is)
        self.assertIsInstance(base, Path)

    def test_db_path_is_under_data(self):
        from core.data_engine import get_db_path
        db = get_db_path()
        self.assertEqual(db.name, "universe.db")
        self.assertEqual(db.parent.name, "data")

    def test_no_hardcoded_project_mip_paths(self):
        """Ensure no hardcoded references to old project remain."""
        source = (PROJECT_ROOT / "core" / "data_engine.py").read_text()
        self.assertNotIn("Project_MIP_Pydroid3", source,
                         "Hardcoded old project path found in data_engine.py!")
        self.assertNotIn("/storage/emulated/0/Documents/Projects", source,
                         "Hardcoded Android storage path found!")


class TestDatabaseAccess(unittest.TestCase):
    """Test database operations — skips if universe.db not provisioned."""

    def setUp(self):
        from core.data_engine import get_db_path
        if not get_db_path().exists():
            self.skipTest("universe.db not provisioned — skipping DB tests")

    def test_connection_opens(self):
        from core.data_engine import get_connection
        conn = get_connection(read_only=True, reuse=False)
        self.assertIsNotNone(conn)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()

    def test_prices_table_exists(self):
        from core.data_engine import get_connection
        conn = get_connection(read_only=True, reuse=False)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='prices'"
        )
        result = cursor.fetchone()
        self.assertIsNotNone(result, "prices table not found in universe.db")
        conn.close()

    def test_read_only_connection_blocks_writes(self):
        """Verify that read_only=True connections strictly forbid database mutations."""
        import sqlite3
        from core.data_engine import get_connection
        conn = get_connection(read_only=True, reuse=False)
        cursor = conn.cursor()
        with self.assertRaises(sqlite3.OperationalError):
            cursor.execute("CREATE TABLE write_safety_probe (x INT);")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
