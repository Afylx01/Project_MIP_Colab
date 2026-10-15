"""
Contract Test Suite: High-Compression Cloud Synchronization & Staging
Validates gzip streaming compression, decompress-on-stage, and Google Drive quota protection.
"""

import os
import sys
import gzip
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from scripts.cloud_sync import (
    is_gzipped_file,
    compress_file,
    decompress_file,
    sync_universe_from_gdrive,
    push_universe_to_gdrive,
)


class TestCompressionSync(unittest.TestCase):
    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_mip_comp_"))
        self.db_path = self.test_dir / "sample.db"
        self.gz_path = self.test_dir / "sample.db.gz"

        # Create a realistic test SQLite database with multiple pages
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE test_bars (id INTEGER PRIMARY KEY, symbol TEXT, date TEXT, close REAL);")
        records = [(i, f"SYM_{i % 50}", f"2026-10-{i % 28 + 1:02d}", 100.0 + (i * 0.1)) for i in range(5000)]
        cur.executemany("INSERT INTO test_bars VALUES (?, ?, ?, ?);", records)
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_is_gzipped_file_detection(self):
        """Validates detection of standard GZIP magic bytes (0x1f 0x8b) vs raw SQLite database."""
        # Uncompressed SQLite database must not be identified as gzip
        self.assertFalse(is_gzipped_file(self.db_path))

        # Compressed file must be identified as gzip
        with open(self.db_path, "rb") as f_in, gzip.open(self.gz_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        self.assertTrue(is_gzipped_file(self.gz_path))

    def test_02_compress_and_decompress_roundtrip(self):
        """Validates exact byte content and SQLite database integrity preservation across streaming compression."""
        orig_bytes, gz_bytes = compress_file(self.db_path, self.gz_path, compresslevel=6)
        self.assertGreater(orig_bytes, 0)
        self.assertGreater(gz_bytes, 0)
        self.assertLess(gz_bytes, orig_bytes)
        self.assertTrue(self.gz_path.exists())

        decomp_db = self.test_dir / "decompressed.db"
        gz_b2, decomp_bytes = decompress_file(self.gz_path, decomp_db)
        self.assertEqual(orig_bytes, decomp_bytes)
        self.assertEqual(gz_bytes, gz_b2)

        # Confirm decompressed database is 100% valid SQLite
        conn = sqlite3.connect(decomp_db)
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        res = cur.fetchone()[0]
        self.assertEqual(res.lower(), "ok")

        cur.execute("SELECT COUNT(*) FROM test_bars;")
        count = cur.fetchone()[0]
        self.assertEqual(count, 5000)
        conn.close()

    def test_03_sync_from_gdrive_decompresses_gz_automatically(self):
        """sync_universe_from_gdrive must recognize a .gz source, decompress it, and stage valid SQLite to destination."""
        compress_file(self.db_path, self.gz_path)

        local_dest = self.test_dir / "local_nvme" / "universe.db"
        ok, status, meta = sync_universe_from_gdrive(
            destination_path=local_dest,
            gdrive_source_path=self.gz_path,
            verbose=False,
        )
        self.assertTrue(ok)
        self.assertEqual(status, "DECOMPRESSED_FROM_GDRIVE_GZ")
        self.assertTrue(local_dest.exists())
        self.assertFalse(is_gzipped_file(local_dest))

        # Check integrity of staged database
        conn = sqlite3.connect(local_dest)
        cur = conn.cursor()
        cur.execute("PRAGMA quick_check;")
        self.assertEqual(cur.fetchone()[0].lower(), "ok")
        conn.close()

    def test_04_push_universe_to_gdrive_compresses_and_cleans_legacy(self):
        """push_universe_to_gdrive must compress local DB, write .gz to Drive, and remove legacy uncompressed file."""
        fake_gdrive_dir = self.test_dir / "fake_drive" / "MIP"
        fake_gdrive_dir.mkdir(parents=True, exist_ok=True)

        # Place legacy uncompressed file in Drive
        legacy_uncompressed = fake_gdrive_dir / "universe.db"
        shutil.copy2(self.db_path, legacy_uncompressed)
        self.assertTrue(legacy_uncompressed.exists())

        target_gz = fake_gdrive_dir / "universe.db.gz"
        ok, status, meta = push_universe_to_gdrive(
            local_db_path=self.db_path,
            gdrive_dest_path=target_gz,
            compress=True,
            clean_uncompressed=True,
            verbose=False,
        )
        self.assertTrue(ok)
        self.assertEqual(status, "BACKED_UP_TO_GDRIVE_GZ")
        self.assertTrue(target_gz.exists())
        self.assertTrue(is_gzipped_file(target_gz))

        # Legacy uncompressed file must be cleaned up to protect user Drive quota
        self.assertFalse(legacy_uncompressed.exists())


if __name__ == "__main__":
    unittest.main()
