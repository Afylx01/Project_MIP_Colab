#!/usr/bin/env python3
"""
Test Suite: Latest EOD Auto-Date Resolution & Data Fetch Hardening
Directive: PROD-RUN-EOD-HARDENING-01

Covers:
  1. Market hours & EOD determination (before/after 18:30 IST)
  2. Weekend regression to preceding Friday
  3. Holiday resolution (e.g., 2026-10-02 Mahatma Gandhi Jayanti)
  4. Missing dates calculation filtering holidays
  5. Multi-day gap resolution beyond calendar
  6. AutoFetchStatus enum consistency
  7. Elimination of sync_res UnboundLocalError on 404/failure
  8. sync_universe returning CURRENT when DB is up-to-date
  9. Bhavcopy parser series whitespace stripping (' EQ' -> 'EQ')
 10. resolve_latest_valid_eod explicit date valid
 11. resolve_latest_valid_eod explicit date missing/invalid
 12. resolve_latest_valid_eod unspecified date contract
 13. resolve_latest_valid_eod fail-closed on stale data
 14. resolve_latest_valid_eod allow_stale flag
 15. Scanner raises StaleDataError when latest EOD unavailable
 16. Scanner raises DataUnavailableError on missing explicit date
 17. ETFMomentumEngine has functional log() method
 18. Benchmark sync dual-source architecture
"""

import sys
import os
import unittest
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

TEST_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TEST_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import pandas as pd
import numpy as np

try:
    from pydroid_core.data_engine import (
        get_base_dir,
        get_connection,
        KNOWN_NSE_HOLIDAYS,
        StaleDataError,
        DataUnavailableError,
        get_expected_latest_eod,
        resolve_latest_valid_eod,
    )
    from pydroid_core.auto_fetch import PydroidAutoFetch, AutoFetchStatus
    from pydroid_core.etf_engine import ETFMomentumEngine
    from pydroid_core.benchmark_validator import get_expected_market_date, BenchmarkSyncResult
    from pydroid_core.scanner import PydroidScanner
    CORE_PKG = "pydroid_core"
except ImportError:
    from core.data_engine import (
        get_base_dir,
        get_connection,
        KNOWN_NSE_HOLIDAYS,
        StaleDataError,
        DataUnavailableError,
        get_expected_latest_eod,
        resolve_latest_valid_eod,
    )
    from core.auto_fetch import PydroidAutoFetch, AutoFetchStatus
    from core.etf_engine import ETFMomentumEngine
    from core.benchmark_validator import get_expected_market_date, BenchmarkSyncResult
    from core.scanner import PydroidScanner
    CORE_PKG = "core"


class TestLatestDateAndAutoFetch(unittest.TestCase):
    def setUp(self):
        self.base_dir = get_base_dir()
        self.fetcher = PydroidAutoFetch(self.base_dir)

    def test_01_expected_latest_eod_market_hours(self):
        """Test expected session before 18:30 IST vs after 18:30 IST on a normal weekday."""
        # 2026-10-07 (Wednesday) at 12:00 IST -> prior completed session is 2026-10-06
        # 12:00 IST is 06:30 UTC
        dt_midday = datetime.datetime(2026, 10, 7, 6, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_midday), "2026-10-06")

        # 2026-10-07 (Wednesday) at 19:00 IST -> completed session is 2026-10-07
        # 19:00 IST is 13:30 UTC
        dt_evening = datetime.datetime(2026, 10, 7, 13, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_evening), "2026-10-07")

    def test_02_expected_latest_eod_weekend(self):
        """Saturday and Sunday must resolve to preceding Friday."""
        # Saturday 2026-10-10 12:00 UTC -> Friday 2026-10-09
        dt_sat = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_sat), "2026-10-09")

        # Sunday 2026-10-11 12:00 UTC -> Friday 2026-10-09
        dt_sun = datetime.datetime(2026, 10, 11, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_sun), "2026-10-09")

    def test_03_expected_latest_eod_holiday(self):
        """Holiday (e.g. 2026-10-02 Mahatma Gandhi Jayanti) resolves to preceding trading day."""
        # 2026-10-02 at 20:00 IST -> October 2 is holiday, resolves to 2026-10-01
        dt_holiday = datetime.datetime(2026, 10, 2, 14, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_holiday), "2026-10-01")

        # Next Monday morning 2026-10-05 before 18:30 IST -> resolves to 2026-10-01
        dt_mon_am = datetime.datetime(2026, 10, 5, 5, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(dt_mon_am), "2026-10-01")

    def test_04_missing_dates_excludes_gandhi_jayanti(self):
        """get_missing_trading_dates must filter out 2026-10-02 holiday."""
        with patch.object(self.fetcher, "log"):
            with patch(f"{CORE_PKG}.data_engine.get_connection") as mock_conn:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = ("2026-10-01",)
                mock_conn.return_value.cursor.return_value = mock_cursor
                dates = self.fetcher.get_missing_trading_dates("2026-10-05")
                self.assertNotIn("2026-10-02", dates)
                self.assertIn("2026-10-05", dates)

    def test_05_missing_dates_multi_day_gap(self):
        """Multi-day gap spanning beyond calendar must compute valid weekdays."""
        with patch.object(self.fetcher, "log"):
            with patch(f"{CORE_PKG}.data_engine.get_connection") as mock_conn:
                mock_cursor = MagicMock()
                mock_cursor.fetchone.return_value = ("2026-10-01",)
                mock_conn.return_value.cursor.return_value = mock_cursor
                dates = self.fetcher.get_missing_trading_dates("2026-10-08")
                self.assertNotIn("2026-10-02", dates)
                self.assertNotIn("2026-10-03", dates)  # Saturday
                self.assertNotIn("2026-10-04", dates)  # Sunday
                for expected in ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]:
                    self.assertIn(expected, dates)

    def test_06_auto_fetch_status_enum(self):
        """AutoFetchStatus enum values must be non-empty strings."""
        for status in [
            AutoFetchStatus.CURRENT,
            AutoFetchStatus.UPDATED,
            AutoFetchStatus.NO_NEW_SESSION,
            AutoFetchStatus.SOURCE_UNAVAILABLE,
            AutoFetchStatus.NETWORK_FAILURE,
            AutoFetchStatus.DATA_INVALID,
            AutoFetchStatus.VALIDATION_FAILURE,
        ]:
            self.assertIsInstance(status.value, str)
            self.assertTrue(len(status.value) > 0)

    def test_07_auto_fetch_no_unbound_sync_res(self):
        """Calling sync_universe when fetch returns empty must not raise UnboundLocalError."""
        with patch.object(self.fetcher, "get_missing_trading_dates", return_value=["2026-10-02"]):
            with patch.object(self.fetcher, "fetch_bhavcopy_for_date", return_value=None):
                result = self.fetcher.sync_universe(target_date="2026-10-02")
                self.assertIsInstance(result, dict)
                self.assertEqual(result.get("status"), AutoFetchStatus.SOURCE_UNAVAILABLE.value)
                self.assertEqual(result.get("dates_fetched"), 0)

    def test_08_auto_fetch_no_missing_dates_returns_current(self):
        """Calling sync_universe when DB is current must return CURRENT status."""
        with patch.object(self.fetcher, "get_missing_trading_dates", return_value=[]):
            result = self.fetcher.sync_universe(target_date="2026-10-01")
            self.assertIsInstance(result, dict)
            self.assertEqual(result.get("status"), AutoFetchStatus.CURRENT.value)
            self.assertEqual(result.get("dates_fetched"), 0)

    def test_09_bhavcopy_standardize_strips_series_whitespace(self):
        """_standardize_bhavcopy must strip whitespace from series column."""
        raw_df = pd.DataFrame({
            "SYMBOL": ["INFY", "TCS", "JUNK"],
            "SERIES": [" EQ", "  BE ", "XX"],
            "DATE1": ["05-OCT-2026", "05-OCT-2026", "05-OCT-2026"],
            "OPEN_PRICE": [1500.0, 3500.0, 10.0],
            "HIGH_PRICE": [1520.0, 3550.0, 11.0],
            "LOW_PRICE": [1490.0, 3480.0, 9.0],
            "CLOSE_PRICE": [1510.0, 3520.0, 10.5],
            "TTL_TRD_QNTY": [100000, 50000, 100],
        })
        std = self.fetcher._standardize_bhavcopy(raw_df, fallback_date="2026-10-05")
        self.assertEqual(len(std), 2)
        self.assertIn("INFY", std["symbol"].values)
        self.assertIn("TCS", std["symbol"].values)
        self.assertNotIn("JUNK", std["symbol"].values)

    def test_10_resolve_latest_valid_eod_explicit_date_valid(self):
        """Explicit date existing in DB must resolve with success."""
        ok, res_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date="2026-10-01")
        self.assertTrue(ok)
        self.assertEqual(res_date, "2026-10-01")
        self.assertEqual(diag.get("status"), "EXPLICIT_DATE_VALIDATED")
        self.assertGreaterEqual(diag.get("symbol_count", 0), 50)

    def test_11_resolve_latest_valid_eod_explicit_date_invalid(self):
        """Explicit date not present in DB must return failure."""
        ok, res_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date="2099-01-01")
        self.assertFalse(ok)
        self.assertEqual(res_date, "")
        self.assertEqual(diag.get("status"), "DATE_UNAVAILABLE")

    def test_12_resolve_latest_valid_eod_unspecified_date(self):
        """Unspecified date must return actual latest DB date when valid."""
        ok, res_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date=None, allow_stale=True)
        self.assertTrue(ok)
        self.assertTrue(len(res_date) == 10)
        self.assertGreaterEqual(diag.get("symbol_count", 0), 50)

    def test_13_resolve_latest_valid_eod_stale_blocked(self):
        """When DB latest is strictly older than expected session and allow_stale=False, must block."""
        with patch(f"{CORE_PKG}.data_engine.get_expected_latest_eod", return_value="2026-10-07"):
            conn = get_connection(read_only=True)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM prices;")
            db_max = cursor.fetchone()[0]

            if db_max < "2026-10-07":
                ok, res_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date=None, allow_stale=False)
                self.assertFalse(ok)
                self.assertEqual(diag.get("status"), "STALE_DATA_BLOCKED")

    def test_14_resolve_latest_valid_eod_stale_allowed_flag(self):
        """When allow_stale=True, resolve_latest_valid_eod returns True even if stale."""
        with patch(f"{CORE_PKG}.data_engine.get_expected_latest_eod", return_value="2099-01-01"):
            ok, res_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date=None, allow_stale=True)
            self.assertTrue(ok)
            self.assertTrue(diag.get("is_stale"))

    def test_15_scanner_stale_data_raises_stale_data_error(self):
        """Scanner must fail closed with StaleDataError when latest market data cannot be acquired."""
        scanner = PydroidScanner(self.base_dir)
        with patch(f"{CORE_PKG}.data_engine.get_expected_latest_eod", return_value="2099-01-01"):
            with patch(f"{CORE_PKG}.scanner.get_expected_latest_eod", return_value="2099-01-01"):
                with self.assertRaises(StaleDataError):
                    scanner.run_scan(as_of_date=None, auto_update_universe=False)

    def test_16_scanner_invalid_date_raises_data_unavailable_error(self):
        """Scanner must raise DataUnavailableError on an unpopulated explicit date."""
        scanner = PydroidScanner(self.base_dir)
        with self.assertRaises(DataUnavailableError):
            scanner.run_scan(as_of_date="1980-01-01", auto_update_universe=False)

    def test_17_etf_momentum_engine_log_method(self):
        """ETFMomentumEngine must have log method that prints without error."""
        engine = ETFMomentumEngine(self.base_dir)
        self.assertTrue(hasattr(engine, "log"))
        try:
            engine.log("Test log message")
        except AttributeError:
            self.fail("ETFMomentumEngine.log raised AttributeError unexpectedly")

    def test_18_benchmark_sync_dual_source(self):
        """sync_benchmark must verify and return structured BenchmarkSyncResult or dict."""
        res = self.fetcher.sync_benchmark(target_date="2026-10-01")
        self.assertIn("status", res)
        self.assertIn(res["status"], [BenchmarkSyncResult.UP_TO_DATE.value, "SUCCESS", "UP_TO_DATE"])


if __name__ == "__main__":
    unittest.main()
