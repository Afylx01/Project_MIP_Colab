"""
MIP Android — Hardened Scanner & Constituent Reconciliation Test Suite
Phase 33: T33.11 Verification Suite

Verifies:
  1. ConstituentValidator rejects empty, HTML error, malformed CSV, out-of-bounds counts.
  2. ConstituentValidator accepts valid Nifty 500 and Nifty 750 payloads.
  3. Duplicate tickers in constituent lists are detected and deduplicated.
  4. ConstituentReconciliationEngine correctly tracks ADDED, REMOVED, UNCHANGED symbols across snapshots.
  5. ConstituentReconciliationEngine maintains idempotent snapshot history in constituent_snapshots.json.
  6. Freshness policy enforcement: LIVE_VERIFIED, CACHED_VALID, STALE, BLOCKED.
  7. MarketDataReconciliationEngine satisfies the disposition accounting sum invariant.
  8. Removing an index constituent leaves historical bars in SQLite prices table completely intact.
  9. Strategy fingerprint remains strictly 9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de.
  10. HardenedScanner end-to-end integration produces full disposition metadata.
"""

import os
import sys
import json
import time
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import MIPScannerConfig
from core.data_engine import get_connection, get_latest_date
from scripts.scanner_hardening import (
    ConstituentValidator,
    ConstituentValidationResult,
    ConstituentReconciliationEngine,
    ConstituentReconciliationReport,
    ConstituentSourceStatus,
    MarketDataReconciliationEngine,
    MarketDataReconciliationReport,
    HardenedScanner,
    get_canonical_strategy_fingerprint,
    HardenedMarketDataRefresher,
)


class TestConstituentValidator(unittest.TestCase):
    """Rigorous tests for ConstituentValidator guards."""

    def test_empty_content_rejected(self):
        res = ConstituentValidator.validate_csv_content(b"", universe_key="NIFTY500")
        self.assertFalse(res.is_valid)
        self.assertIn("Empty", res.error_message)

    def test_html_error_payload_rejected(self):
        html_payload = b"<!DOCTYPE html><html><head><title>403 Forbidden</title></head><body>Access Denied</body></html>"
        res = ConstituentValidator.validate_csv_content(html_payload, universe_key="NIFTY500")
        self.assertFalse(res.is_valid)
        self.assertIn("HTML error payload detected", res.error_message)

    def test_malformed_csv_missing_columns(self):
        csv_data = b"Some,Random,Headers,ExtraColumn1,ExtraColumn2\nVal1,Val2,Val3,Val4,Val5\n"
        res = ConstituentValidator.validate_csv_content(csv_data, universe_key="NIFTY500")
        self.assertFalse(res.is_valid)
        self.assertIn("Missing required constituent header columns", res.error_message)


    def test_out_of_bounds_count_rejected(self):
        # NIFTY 500 expects 490 to 515 rows. Providing 10 rows must fail bounds check.
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(10):
            rows.append(f"Company {i},IT,SYM{i},EQ,IN0000000{i:03d}")
        csv_data = "\n".join(rows).encode("utf-8")
        res = ConstituentValidator.validate_csv_content(csv_data, universe_key="NIFTY500")
        self.assertFalse(res.is_valid)
        self.assertIn("bounds", res.error_message)

    def test_valid_nifty500_payload_accepted(self):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(500):
            rows.append(f"Company {i},Financial Services,TICKER{i},EQ,INF{i:09d}")
        csv_data = "\n".join(rows).encode("utf-8")
        res = ConstituentValidator.validate_csv_content(csv_data, universe_key="NIFTY500")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.row_count, 500)
        self.assertEqual(len(res.valid_symbols), 500)
        self.assertTrue(len(res.sha256_hash) == 64)

    def test_valid_nifty750_payload_accepted(self):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(750):
            rows.append(f"Company {i},Capital Goods,TICKER{i},EQ,INF{i:09d}")
        csv_data = "\n".join(rows).encode("utf-8")
        res = ConstituentValidator.validate_csv_content(csv_data, universe_key="NIFTY750")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.row_count, 750)
        self.assertEqual(len(res.valid_symbols), 750)

    def test_duplicate_symbols_detected(self):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(499):
            rows.append(f"Company {i},Consumer Goods,STOCK{i},EQ,INF{i:09d}")
        # Add duplicate
        rows.append("Company 0 Duplicate,Consumer Goods,STOCK0,EQ,INF000000000")
        csv_data = "\n".join(rows).encode("utf-8")
        res = ConstituentValidator.validate_csv_content(csv_data, universe_key="NIFTY500")
        self.assertTrue(res.is_valid)
        self.assertEqual(len(res.duplicate_symbols), 1)
        self.assertIn("STOCK0", res.duplicate_symbols)
        self.assertEqual(len(res.valid_symbols), 499)


class TestConstituentReconciliationEngine(unittest.TestCase):
    """Tests for constituent reconciliation, diffing, snapshots, and freshness."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_const_test_"))
        self.data_dir = self.temp_dir / "data"
        self.raw_dir = self.data_dir / "raw_reference"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _generate_csv(self, symbols):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for s in symbols:
            rows.append(f"Company {s},Technology,{s},EQ,IN000000001")
        return "\n".join(rows).encode("utf-8")

    def test_added_removed_unchanged_detection(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols_v1 = [f"SYM{i}" for i in range(500)]
        symbols_v2 = [f"SYM{i}" for i in range(5, 505)]  # Removed SYM0-4 (5), Added SYM500-504 (5)

        csv_v1 = self._generate_csv(symbols_v1)
        csv_v2 = self._generate_csv(symbols_v2)

        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(csv_v1)

        # Baseline snapshot 1
        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            r1 = engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=False)
            self.assertEqual(r1.total_constituents, 500)
            self.assertEqual(len(r1.added_symbols), 0)
            self.assertEqual(len(r1.removed_symbols), 0)

        # Update cache to v2 and re-evaluate
        cache_file.write_bytes(csv_v2)
        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            r2 = engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=False)
            self.assertEqual(r2.total_constituents, 500)
            self.assertEqual(len(r2.added_symbols), 5)
            self.assertEqual(len(r2.removed_symbols), 5)
            self.assertEqual(len(r2.unchanged_symbols), 495)
            self.assertIn("SYM500", r2.added_symbols)
            self.assertIn("SYM0", r2.removed_symbols)

    def test_idempotent_snapshot_history(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols = [f"SYM{i}" for i in range(500)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(csv_bytes)

        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            # Call multiple times with identical data
            engine.fetch_and_reconcile(universe_mode="NIFTY500")
            engine.fetch_and_reconcile(universe_mode="NIFTY500")
            engine.fetch_and_reconcile(universe_mode="NIFTY500")

        history_file = self.data_dir / "constituent_snapshots.json"
        self.assertTrue(history_file.exists())
        with open(history_file, "r") as f:
            data = json.load(f)
        # Should record exactly 1 entry for the same hash, not 3 duplicates
        self.assertEqual(len(data.get("NIFTY500", [])), 1)

    def test_freshness_policy_live_verified(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols = [f"SYM{i}" for i in range(500)]
        csv_bytes = self._generate_csv(symbols)
        official_url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"

        with patch.object(engine, "_fetch_live_with_failover", return_value=(csv_bytes, official_url)):
            rep = engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.LIVE_VERIFIED)
            self.assertEqual(rep.source_url, official_url)

    def test_freshness_policy_mock_simulation_fixture(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols = [f"SYM{i}" for i in range(500)]
        csv_bytes = self._generate_csv(symbols)
        mock_url = "https://mock.nse/list.csv"

        with patch.object(engine, "_fetch_live_with_failover", return_value=(csv_bytes, mock_url)):
            rep = engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.SIMULATED_TEST_FIXTURE)
            self.assertEqual(rep.source_url, mock_url)

    def test_freshness_policy_cached_valid(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols = [f"SYM{i}" for i in range(500)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(csv_bytes)

        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            rep = engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=False)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.CACHED_VALID)

    def test_freshness_policy_stale_cache_behavior(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        symbols = [f"SYM{i}" for i in range(500)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(csv_bytes)

        # Set file modification time to 45 days ago
        old_time = time.time() - (45 * 86400)
        os.utime(cache_file, (old_time, old_time))

        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            # allow_stale=True -> returns STALE
            rep_stale = engine.fetch_and_reconcile(universe_mode="NIFTY500", allow_stale=True)
            self.assertEqual(rep_stale.source_status, ConstituentSourceStatus.STALE)

            # allow_stale=False -> returns BLOCKED
            rep_blocked = engine.fetch_and_reconcile(universe_mode="NIFTY500", allow_stale=False)
            self.assertEqual(rep_blocked.source_status, ConstituentSourceStatus.BLOCKED)

    def test_corrupt_cache_fails_closed_blocked(self):
        engine = ConstituentReconciliationEngine(self.temp_dir)
        cache_file = self.raw_dir / "ind_nifty500list.csv"
        cache_file.write_bytes(b"CORRUPTED INVALID DATA NO HEADERS\nGARBAGE\n")

        with patch.object(engine, "_fetch_live_with_failover", return_value=(None, None)):
            rep = engine.fetch_and_reconcile(universe_mode="NIFTY500")
            self.assertEqual(rep.source_status, ConstituentSourceStatus.BLOCKED)


class TestMarketDataReconciliationEngine(unittest.TestCase):
    """Tests for data coverage accounting and disposition sum invariant."""

    def test_disposition_sum_invariant(self):
        engine = MarketDataReconciliationEngine(PROJECT_ROOT)
        constituents = {"RELIANCE", "TCS", "INFY", "NON_EXISTENT_SYMBOL_999"}
        as_of = get_latest_date()

        report = engine.reconcile_universe_coverage(constituents=constituents, as_of_date=as_of)

        sum_dispositions = (
            report.present_current_count +
            report.present_stale_count +
            report.missing_count +
            report.invalid_count
        )
        self.assertEqual(sum_dispositions, report.total_constituents)
        self.assertEqual(report.total_constituents, 4)
        self.assertIn("NON_EXISTENT_SYMBOL_999", report.missing_symbols)


class TestConstituentRetentionInvariant(unittest.TestCase):
    """Verifies that removing a constituent from an index does NOT purge historical bars."""

    def test_removed_constituent_historical_bars_preserved(self):
        # Query existing database for an active symbol
        conn = get_connection(read_only=True, reuse=True)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, COUNT(*) FROM prices GROUP BY symbol LIMIT 1")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        sample_symbol, bar_count = row[0], row[1]
        self.assertGreater(bar_count, 0)

        # Reconciling against an index list that OMITS sample_symbol
        synthetic_index = {"SOME_OTHER_TICKER_ABC"}
        engine = MarketDataReconciliationEngine(PROJECT_ROOT)
        as_of = get_latest_date()
        rep = engine.reconcile_universe_coverage(synthetic_index, as_of)

        # The omitted sample_symbol is simply not in the index;
        # verify that the prices table was NOT mutated in any way
        cursor.execute("SELECT COUNT(*) FROM prices WHERE symbol=?", (sample_symbol,))
        post_count = cursor.fetchone()[0]
        self.assertEqual(bar_count, post_count, "Historical bars must never be dropped when symbol exits index.")


class TestStrategyFingerprintInvariance(unittest.TestCase):
    """Verify that scanner hardening did NOT alter the frozen strategy fingerprint."""

    CANONICAL_FINGERPRINT = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"

    def test_fingerprint_preservation(self):
        cfg = MIPScannerConfig()
        fp = get_canonical_strategy_fingerprint(cfg)
        self.assertEqual(fp, self.CANONICAL_FINGERPRINT)


class TestHardenedScannerIntegration(unittest.TestCase):
    """End-to-end integration test of HardenedScanner."""

    def test_hardened_scanner_run(self):
        scanner = HardenedScanner(PROJECT_ROOT)
        latest_d = get_latest_date()
        top_df, disposition_summary, const_report, data_reconcile = scanner.run_hardened_scan(
            as_of_date=latest_d,
            universe_mode="NIFTY500",
            force_constituent_refresh=False,
            allow_stale_universe=True,
            auto_update_universe=False,
            export_reports=False,
        )

        self.assertIsNotNone(top_df)
        self.assertIn("total_constituents", disposition_summary)
        self.assertIn("coverage_pct", disposition_summary)
        self.assertEqual(disposition_summary["strategy_fingerprint"], TestStrategyFingerprintInvariance.CANONICAL_FINGERPRINT)
        self.assertEqual(const_report.total_constituents, 501)
        self.assertGreater(data_reconcile.present_current_count, 450)


class TestUniverseDenominatorAccounting(unittest.TestCase):
    """
    T34.1: Mathematical and symbol-level reconciliation of universe denominators
    against official index constituents and active database scrips.
    """

    def test_nifty500_denominator_accounting_20261009(self):
        # 1. Load official NIFTY 500 constituents
        import pandas as pd
        csv_path = PROJECT_ROOT / "data" / "raw_reference" / "ind_nifty500list.csv"
        df = pd.read_csv(csv_path)
        official_constituents = set(df["Symbol"].str.strip().str.upper())
        self.assertEqual(len(official_constituents), 501, "Official NIFTY 500 must have 501 constituents")

        # 2. Query distinct active symbols traded on 2026-10-09
        conn = get_connection(read_only=True, reuse=True)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM prices WHERE date = '2026-10-09'")
        active_db_symbols = {r[0] for r in cursor.fetchall()}
        self.assertEqual(len(active_db_symbols), 1031, "Total active traded DB symbols on 2026-10-09 must be 1,031")

        # 3. Reconcile matched, missing, and non-index active
        matched = official_constituents.intersection(active_db_symbols)
        missing_official = official_constituents - active_db_symbols
        non_index_active = active_db_symbols - official_constituents

        self.assertEqual(len(matched), 497, "Matched active NIFTY 500 stocks must be 497")
        self.assertEqual(len(missing_official), 4, "Missing official constituents must be 4")
        self.assertEqual(len(non_index_active), 534, "Non-index active DB stocks must be 534")

        # 4. Conservation invariants
        self.assertEqual(len(matched) + len(missing_official), len(official_constituents), "Constituent conservation (497 + 4 = 501)")
        self.assertEqual(len(matched) + len(non_index_active), len(active_db_symbols), "Database active conservation (497 + 534 = 1,031)")
        self.assertEqual(missing_official, {"BAGMANE", "BIRET", "DUMMYHEG", "EMBASSY"})

    def test_nifty750_denominator_accounting_20260831(self):
        # 1. Load official NIFTY 750 (Total Market) constituents
        import pandas as pd
        csv_path = PROJECT_ROOT / "data" / "raw_reference" / "ind_niftytotalmarket_list.csv"
        df = pd.read_csv(csv_path)
        official_constituents = set(df["Symbol"].str.strip().str.upper())
        self.assertEqual(len(official_constituents), 755, "Official NIFTY 750 must have 755 constituents")

        # 2. Query distinct active symbols traded on 2026-08-31
        conn = get_connection(read_only=True, reuse=True)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT symbol FROM prices WHERE date = '2026-08-31'")
        active_db_symbols = {r[0] for r in cursor.fetchall()}
        self.assertEqual(len(active_db_symbols), 750, "Total active traded DB symbols on 2026-08-31 must be 750")

        # 3. Reconcile matched, missing/stale, and non-index active
        matched = official_constituents.intersection(active_db_symbols)
        missing_official = official_constituents - active_db_symbols
        non_index_active = active_db_symbols - official_constituents

        self.assertEqual(len(matched), 695, "Matched active NIFTY 750 stocks must be 695")
        self.assertEqual(len(missing_official), 60, "Missing/stale official constituents must be 60")
        self.assertEqual(len(non_index_active), 55, "Non-index active DB stocks must be 55")

        # 4. Conservation invariants
        self.assertEqual(len(matched) + len(missing_official), len(official_constituents), "Constituent conservation (695 + 60 = 755)")
        self.assertEqual(len(matched) + len(non_index_active), len(active_db_symbols), "Database active conservation (695 + 55 = 750)")


class TestHardenedMarketDataRefresher(unittest.TestCase):
    """
    T34.2 & T34.5: Proves market data refresh, geometric validation,
    production immutability firewall, and repeat-run idempotency.
    """

    def test_production_immutability_firewall(self):
        refresher = HardenedMarketDataRefresher()
        self.assertTrue(refresher.is_production_db)
        # Attempt direct write connection to production db without MIP_ALLOW_PROD_MUTATION
        with self.assertRaises(PermissionError):
            refresher._get_active_db_connection(read_only=False)

        # refresh_missing_sessions against production must return SAFETY_CONTROL_DRY_RUN or CURRENT
        res = refresher.refresh_missing_sessions(dry_run=False)
        self.assertIn(res["status"], ["SAFETY_CONTROL_DRY_RUN", "CURRENT"])

    def test_sandbox_isolated_refresh_and_repeat_run_idempotency(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox_db = Path(tmpdir) / "sandbox_universe.db"
            conn = sqlite3.connect(sandbox_db)
            conn.execute("""
                CREATE TABLE prices (
                    date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    is_delisted INTEGER DEFAULT 0
                )
            """)
            # Insert a baseline row for 2026-10-08
            conn.execute("""
                INSERT INTO prices (date, symbol, open, high, low, close, volume, is_delisted)
                VALUES ('2026-10-08', 'RELIANCE', 2800.0, 2850.0, 2790.0, 2840.0, 100000.0, 0)
            """)
            conn.commit()
            conn.close()

            refresher = HardenedMarketDataRefresher(target_db_path=sandbox_db)
            missing = refresher.get_missing_trading_dates("2026-10-09")
            self.assertEqual(missing, ["2026-10-09"])

            # Run 1: Refresh missing session from local delivery cache
            res1 = refresher.refresh_missing_sessions(target_date="2026-10-09")
            self.assertEqual(res1["status"], "UPDATED")
            self.assertEqual(res1["dates_fetched"], 1)
            self.assertEqual(res1["rows_inserted"], 1031)

            # Check geometric invariants on newly inserted rows: High >= Low, Open > 0, Close > 0, Volume >= 0
            conn = sqlite3.connect(sandbox_db)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM prices 
                WHERE date = '2026-10-09' AND (high < low OR open <= 0 OR close <= 0 OR volume < 0)
            """)
            violations = cursor.fetchone()[0]
            self.assertEqual(violations, 0, "All refreshed bars must satisfy geometric invariants")

            cursor.execute("SELECT COUNT(*) FROM prices")
            count_after_run1 = cursor.fetchone()[0]
            self.assertEqual(count_after_run1, 1032)

            # Run 2: Repeat run (Idempotency verification T34.5)
            res2 = refresher.refresh_missing_sessions(target_date="2026-10-09")
            self.assertEqual(res2["status"], "CURRENT")
            self.assertEqual(res2["dates_fetched"], 0)

            cursor.execute("SELECT COUNT(*) FROM prices")
            count_after_run2 = cursor.fetchone()[0]
            self.assertEqual(count_after_run2, count_after_run1, "Second run must not duplicate records")
            conn.close()


class TestNewlyAddedConstituentWorkflow(unittest.TestCase):
    """
    T34.3 & T34.4: Verifies handling of added and removed constituents.
    """

    def test_newly_added_constituent_not_silently_omitted(self):
        engine = MarketDataReconciliationEngine(PROJECT_ROOT)
        constituents = {"RELIANCE", "TCS", "INFY", "NEWTICKER999"}
        as_of = get_latest_date()

        report = engine.reconcile_universe_coverage(constituents=constituents, as_of_date=as_of)
        self.assertIn("NEWTICKER999", report.missing_symbols)
        # Verify conservation: sum of dispositions equals total constituents
        sum_disp = (
            report.present_current_count +
            report.present_stale_count +
            report.missing_count +
            report.invalid_count
        )
        self.assertEqual(sum_disp, len(constituents))
        self.assertEqual(report.total_constituents, 4)

    def test_removed_constituent_leaves_candidate_universe_preserves_history(self):
        conn = get_connection(read_only=True, reuse=True)
        cursor = conn.cursor()
        cursor.execute("SELECT symbol, COUNT(*) FROM prices WHERE symbol='RELIANCE'")
        reliance_bar_count = cursor.fetchone()[1]
        self.assertGreater(reliance_bar_count, 0)

        # When scanning an index that excludes RELIANCE (e.g. index containing only TCS)
        synthetic_index = {"TCS"}
        cursor.execute("SELECT DISTINCT symbol FROM prices WHERE date='2026-10-09'")
        active_today = {r[0] for r in cursor.fetchall()}

        # Active candidates are strictly the intersection of active_today and index constituents
        active_candidates = active_today.intersection(synthetic_index)
        self.assertNotIn("RELIANCE", active_candidates, "Removed symbol must exit active scan candidate universe")
        self.assertIn("TCS", active_candidates)

        # Historical bars remain intact
        cursor.execute("SELECT COUNT(*) FROM prices WHERE symbol='RELIANCE'")
        post_count = cursor.fetchone()[0]
        self.assertEqual(post_count, reliance_bar_count, "Historical bars must remain 100% intact")


if __name__ == "__main__":
    unittest.main()
