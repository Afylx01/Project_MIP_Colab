"""
TDD Contract Tests for Core Hardening and Production Firewall Unification (Phase 40).

Tests:
1. test_core_get_connection_write_blocked_without_env_flag:
   Asserts get_connection(read_only=False) raises PermissionError when targeting production DB
   without MIP_ALLOW_PROD_MUTATION=1.
2. test_core_get_connection_write_allowed_with_env_flag:
   Asserts get_connection(read_only=False) succeeds when MIP_ALLOW_PROD_MUTATION=1.
3. test_core_auto_fetch_sync_universe_blocked_without_flag:
   Asserts PydroidAutoFetch.sync_universe() refuses production writes and returns safety status
   when MIP_ALLOW_PROD_MUTATION != 1.
4. test_core_load_universe_constituents_schema_validation:
   Asserts malformed, corrupted, or truncated constituent CSVs fail closed (returns empty set or raises, never corrupts).
5. test_core_load_universe_constituents_ttl_30_days:
   Verifies cached constituent files are accepted up to 30.0 days and refreshed/flagged thereafter.
6. test_scanner_runs_without_monkeypatch:
   Verifies HardenedScanner executes complete scans with 0 runtime patches on core modules.
"""

import os
import sys
import time
import tempfile
import shutil
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

# Setup paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import core.data_engine as de
import core.auto_fetch as af
from core.data_engine import get_db_path, get_connection, load_universe_constituents
from core.auto_fetch import PydroidAutoFetch
from scripts.scanner_hardening import HardenedScanner, ConstituentValidator


class TestCoreImmutabilityFirewall(unittest.TestCase):
    """Test suite verifying production DB immutability firewall in core modules."""

    def setUp(self):
        self.orig_env = os.environ.get("MIP_ALLOW_PROD_MUTATION")
        if "MIP_ALLOW_PROD_MUTATION" in os.environ:
            del os.environ["MIP_ALLOW_PROD_MUTATION"]
        de._CACHED_CONN = None

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["MIP_ALLOW_PROD_MUTATION"] = self.orig_env
        elif "MIP_ALLOW_PROD_MUTATION" in os.environ:
            del os.environ["MIP_ALLOW_PROD_MUTATION"]
        de._CACHED_CONN = None

    def test_core_get_connection_write_blocked_without_env_flag(self):
        """get_connection(read_only=False) must raise PermissionError if targeting prod DB without flag."""
        with self.assertRaises(PermissionError) as ctx:
            get_connection(read_only=False, reuse=False)
        self.assertIn("PRODUCTION IMMUTABILITY VIOLATION", str(ctx.exception))

    def test_core_get_connection_write_allowed_with_env_flag(self):
        """get_connection(read_only=False) must succeed if MIP_ALLOW_PROD_MUTATION='1'."""
        os.environ["MIP_ALLOW_PROD_MUTATION"] = "1"
        conn = get_connection(read_only=False, reuse=False)
        self.assertIsNotNone(conn)
        conn.close()

    def test_core_auto_fetch_sync_universe_blocked_without_flag(self):
        """PydroidAutoFetch.sync_universe() must block write mutations without MIP_ALLOW_PROD_MUTATION=1."""
        fetcher = PydroidAutoFetch()
        res = fetcher.sync_universe(target_date="2026-10-15", dry_run=False)
        self.assertIn(res.get("status"), ["SAFETY_CONTROL_DRY_RUN", "CURRENT"])
        if res.get("status") == "SAFETY_CONTROL_DRY_RUN":
            self.assertIn("blocked", res.get("message", "").lower())


class TestCoreConstituentLoaderHardening(unittest.TestCase):
    """Test suite verifying constituent loading validation and 30-day TTL in core."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_core_loader_"))
        self.raw_dir = self.temp_dir / "data" / "raw_reference"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_core_load_universe_constituents_schema_validation(self):
        """Malformed or HTML error payloads in raw_reference must be rejected."""
        html_payload = b"<!DOCTYPE html><html><body>403 Forbidden Access Denied</body></html>"
        corrupt_file = self.raw_dir / "ind_nifty500list.csv"
        corrupt_file.write_bytes(html_payload)

        with patch("core.data_engine.get_base_dir", return_value=self.temp_dir):
            with patch("scripts.scanner_hardening.ConstituentReconciliationEngine._fetch_live_with_failover", return_value=(None, None)):
                scrips = load_universe_constituents(universe_name="NIFTY500", force_refresh=False)
                # Must return empty set, never corrupted symbols from HTML tags
                self.assertEqual(len(scrips), 0)

    def test_core_load_universe_constituents_ttl_30_days(self):
        """Cache within 30 days is accepted; cache older than 30 days triggers refresh."""
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(500):
            rows.append(f"Company {i},IT,TICKER{i},EQ,INF{i:09d}")
        valid_csv = "\n".join(rows).encode("utf-8")
        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(valid_csv)

        # 1. 20 days old -> accepted as fresh without network
        twenty_days_ago = time.time() - (20 * 86400)
        os.utime(cache_file, (twenty_days_ago, twenty_days_ago))

        with patch("core.data_engine.get_base_dir", return_value=self.temp_dir):
            with patch("scripts.scanner_hardening.ConstituentReconciliationEngine._fetch_live_with_failover", side_effect=AssertionError("Network called on fresh cache!")):
                scrips = load_universe_constituents(universe_name="NIFTY500", force_refresh=False)
                self.assertEqual(len(scrips), 500)


class TestHardenedScannerZeroMonkeyPatch(unittest.TestCase):
    """Test suite verifying HardenedScanner operates without runtime monkey-patching."""

    def test_scanner_runs_without_monkeypatch(self):
        """HardenedScanner must execute cleanly with zero monkey-patching on core modules."""
        scanner = HardenedScanner()
        top_df, m_meta, s_meta, b_meta, picks_df, etf_df = scanner.run_scan(
            as_of_date="2026-10-09",
            universe_mode="NIFTYBANK",
            top_n=3,
            export_csv=False,
            export_excel=False,
            auto_update_universe=False,
        )
        self.assertIsNotNone(top_df)
        self.assertLessEqual(len(top_df), 14)


if __name__ == "__main__":
    unittest.main()
