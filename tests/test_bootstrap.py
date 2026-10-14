"""
MIP Android — Test Database Provisioning State Machine
Directive: STAGE-7-STAGE-19-TEST-01
"""

import hashlib
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest

from scripts.bootstrap_universe_db import BootstrapStateMachine, CANONICAL_DB_SHA256


class TestBootstrapStateMachine(unittest.TestCase):
    """Verifies state machine transitions, validation, and rollback semantics."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="mip_test_bootstrap_"))
        self.target_db = self.test_dir / "universe.db"
        self.source_db = Path("/sdcard/Documents/Projects/Project_MIP_Pydroid3/data/universe.db")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_existing_matching_db(self):
        # Create a small valid SQLite DB and compute its hash
        conn = sqlite3.connect(str(self.target_db))
        conn.execute("CREATE TABLE prices (date TEXT, symbol TEXT);")
        for i in range(100005):
            conn.execute("INSERT INTO prices VALUES ('2026-10-01', 'RELIANCE');")
        conn.commit()
        conn.close()

        h = hashlib.sha256(self.target_db.read_bytes()).hexdigest()
        sm = BootstrapStateMachine(target_path=self.target_db, expected_sha=h)
        success = sm.bootstrap()
        self.assertTrue(success)
        self.assertEqual(sm.current_state, "READY")

    def test_wrong_sha_rejection_and_cleanup(self):
        # Provide wrong expected SHA
        sm = BootstrapStateMachine(
            target_path=self.target_db,
            expected_sha="0000000000000000000000000000000000000000000000000000000000000000"
        )
        # Create a dummy source file
        dummy_source = self.test_dir / "dummy_source.db"
        dummy_source.write_bytes(b"corrupted or wrong database contents")

        success = sm.bootstrap(source=str(dummy_source))
        self.assertFalse(success)
        self.assertEqual(sm.current_state, "FAILED")
        self.assertFalse(self.target_db.exists(), "Target file must not be installed on SHA failure")
        
        # Verify no temp files remain
        tmp_files = list(self.test_dir.glob("*.tmp*"))
        self.assertEqual(len(tmp_files), 0, f"Leaked temp files: {tmp_files}")

    def test_corrupted_sqlite_validation_failure(self):
        # File with correct hash expectation but invalid sqlite structure
        dummy_source = self.test_dir / "bad_sqlite.db"
        dummy_source.write_bytes(b"not a valid sqlite header format at all")
        h = hashlib.sha256(dummy_source.read_bytes()).hexdigest()

        sm = BootstrapStateMachine(target_path=self.target_db, expected_sha=h)
        success = sm.bootstrap(source=str(dummy_source))
        self.assertFalse(success)
        self.assertEqual(sm.current_state, "FAILED")
        self.assertFalse(self.target_db.exists(), "Target file must not be installed on validation failure")


if __name__ == "__main__":
    unittest.main()
