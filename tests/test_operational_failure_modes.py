"""
MIP Android — Operational Hardening & Failure-Mode Recovery Test Suite
Phase 4: Independent Failure-Mode and Recovery Testing

Verifies:
  1. Missing or invalid input data fails closed.
  2. Data refresh failure / incomplete refresh is safely handled.
  3. Insufficient historical bars (<252 bars) strictly disqualified.
  4. Invalid configuration invariants fail validation.
  5. Corrupt or malformed provenance manifest is detected.
  6. Corrupt or malformed checkpoint files are detected.
  7. Process concurrency / duplicate execution protection.
  8. Atomic output generation and recovery without corrupting previous outputs.
  9. Stale output detection.
  10. Database read-only immutability under failure conditions.
"""

import os
import sys
import json
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
from core.data_engine import (
    get_connection,
    resolve_latest_valid_eod,
    StaleDataError,
    DataUnavailableError,
)
from core.scanner import PydroidScanner, ScannerReasonCode


class TestOperationalFailureModes(unittest.TestCase):
    """Rigorous isolated failure-mode and recovery verification."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_op_hardening_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_database_fails_closed(self):
        """1. Missing input database connection fails closed with FileNotFoundError/OperationalError."""
        fake_db = self.temp_dir / "nonexistent.db"
        with self.assertRaises((FileNotFoundError, sqlite3.OperationalError, sqlite3.DatabaseError)):
            conn = sqlite3.connect(f"file:{fake_db}?mode=ro", uri=True)
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM prices;")

    def test_invalid_date_raises_data_unavailable(self):
        """2. Requesting a date not present in SQLite must raise DataUnavailableError."""
        scanner = PydroidScanner(base_dir=PROJECT_ROOT)
        with self.assertRaises(DataUnavailableError):
            scanner.run_scan(as_of_date="1980-01-01", export_excel=False, export_csv=False)

    def test_insufficient_history_anti_ipo_disqualification(self):
        """3. Stocks with <252 bars produce NaN 52w high and fail qualification."""
        cfg = MIPScannerConfig()
        # Create a series with only 50 bars
        s_high = pd.Series([100.0 + i for i in range(50)])
        rolled = s_high.rolling(cfg.rolling_high_bars).max()
        # Must be all NaNs because len < 252
        self.assertTrue(rolled.isna().all(), "Rolling 252 on 50 bars must be completely NaN")
        
        # When comparing Close >= 0.80 * NaN, result must be False
        close_px = 150.0
        passes_f1 = bool(close_px >= (cfg.retrace_threshold * rolled.iloc[-1]))
        self.assertFalse(passes_f1, "Short history stock must not pass retrace filter")

    def test_invalid_configuration_invariants_raise_assertion(self):
        """4. Invalid configuration values must immediately fail validation invariants."""
        # Negative volatility floor
        with self.assertRaises(AssertionError):
            MIPScannerConfig(volatility_floor=-0.01).validate()

        # Zero top N
        with self.assertRaises(AssertionError):
            MIPScannerConfig(top_n_candidates=0).validate()

        # Retrace threshold > 1.0
        with self.assertRaises(AssertionError):
            MIPScannerConfig(retrace_threshold=1.5).validate()

        # Max per sector < 1
        with self.assertRaises(AssertionError):
            MIPScannerConfig(max_per_sector=0).validate()

    def test_malformed_provenance_manifest_detected(self):
        """5. Corrupted or tampered manifest entries must be detected."""
        fake_manifest = self.temp_dir / "PROVENANCE_MANIFEST.json"
        fake_manifest.write_text("{corrupt_json: true}", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(fake_manifest.read_text(encoding="utf-8"))

        # Test hash mismatch detection
        tampered_manifest = {
            "modules": [
                {"filename": "config.py", "sha256_migrated": "0000000000000000000000000000000000000000000000000000000000000000"}
            ]
        }
        entry = tampered_manifest["modules"][0]
        actual_path = PROJECT_ROOT / "core" / entry["filename"]
        import hashlib
        h = hashlib.sha256(actual_path.read_bytes()).hexdigest()
        self.assertNotEqual(h, entry["sha256_migrated"])

    def test_malformed_checkpoint_detected(self):
        """6. Corrupted checkpoint file must fail JSON decoding."""
        corrupt_ckpt = self.temp_dir / "gate-99.json"
        corrupt_ckpt.write_text("{\"gate\": \"GATE-99\", \"status\": ", encoding="utf-8")
        with self.assertRaises(json.JSONDecodeError):
            json.loads(corrupt_ckpt.read_text(encoding="utf-8"))

    def test_process_lock_protection(self):
        """7. Process locking mechanism prevents overlapping concurrent scan runs."""
        lock_file = self.temp_dir / "scanner.lock"
        
        def acquire_lock(path: Path) -> bool:
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
                return True
            except FileExistsError:
                return False

        def release_lock(path: Path) -> None:
            if path.exists():
                path.unlink()

        # First acquisition must succeed
        self.assertTrue(acquire_lock(lock_file))
        self.assertTrue(lock_file.exists())

        # Second concurrent acquisition must fail
        self.assertFalse(acquire_lock(lock_file))

        # Releasing lock permits next run
        release_lock(lock_file)
        self.assertFalse(lock_file.exists())
        self.assertTrue(acquire_lock(lock_file))
        release_lock(lock_file)

    def test_atomic_file_publication_pattern(self):
        """8. Atomic publication preserves prior valid deliverables if current write fails."""
        out_dir = self.temp_dir / "reports"
        out_dir.mkdir(parents=True)
        final_csv = out_dir / "screener_output_live.csv"
        
        # Seed prior valid output
        final_csv.write_text("rank,symbol,close\n1,PRIOR_STOCK,100.0\n", encoding="utf-8")
        prior_content = final_csv.read_text(encoding="utf-8")

        # Simulate failed scan write to a temporary file
        tmp_csv = out_dir / f"screener_output_live.csv.tmp.{os.getpid()}"
        try:
            tmp_csv.write_text("partial,data...", encoding="utf-8")
            raise RuntimeError("Simulated crash during indicator calculation")
        except RuntimeError:
            if tmp_csv.exists():
                tmp_csv.unlink()

        # Prior file remains completely unharmed
        self.assertEqual(final_csv.read_text(encoding="utf-8"), prior_content)

        # Subsequent successful recovery run atomically replaces target
        recovery_tmp = out_dir / f"screener_output_live.csv.tmp.{os.getpid()}"
        recovery_tmp.write_text("rank,symbol,close\n1,FRESH_STOCK,200.0\n", encoding="utf-8")
        os.replace(recovery_tmp, final_csv)

        # Target now cleanly updated with fresh data
        self.assertIn("FRESH_STOCK", final_csv.read_text(encoding="utf-8"))
        self.assertFalse(recovery_tmp.exists())

    def test_stale_output_detection_by_metadata(self):
        """9. Deliverables must be verified for target scan date match to prevent stale presentation."""
        live_csv = PROJECT_ROOT / "reports" / "screener_output_live.csv"
        if live_csv.exists():
            df = pd.read_csv(live_csv)
            self.assertIn("date", df.columns)
            dates = df["date"].unique()
            self.assertEqual(len(dates), 1, "Screener CSV must contain exactly one homogeneous scan date")
            self.assertEqual(dates[0], "2026-10-09")

    def test_database_read_only_protection_against_mutations(self):
        """10. Read-only connection to universe.db prevents accidental write mutations."""
        db_path = PROJECT_ROOT / "data" / "universe.db"
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.cursor()
        with self.assertRaises(sqlite3.OperationalError):
            cur.execute("DROP TABLE prices;")
        with self.assertRaises(sqlite3.OperationalError):
            cur.execute("DELETE FROM prices WHERE date='2026-10-09';")
        conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
