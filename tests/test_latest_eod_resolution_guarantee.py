"""
Contract Test Suite: Authoritative Latest Actual Trading Day EOD Resolution Guarantee
Validates that Project MIP scanner authoritatively identifies and executes on the
latest completed trading session of EOD, integrating real-time IST clock thresholds,
trading_calendar.txt sessions, statutory exchange holidays, and fail-closed freshness gates.
"""

import unittest
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import sys
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.data_engine import (
    get_expected_latest_eod,
    resolve_latest_valid_eod,
    get_latest_date,
    load_trading_calendar,
    StaleDataError,
    DataUnavailableError,
)
from core.scanner import PydroidScanner


class TestLatestEODResolutionGuarantee(unittest.TestCase):
    def setUp(self):
        self.cal = load_trading_calendar()
        self.assertGreater(len(self.cal), 100, "Trading calendar must contain sessions.")

    def test_01_midday_trading_day_resolves_to_prior_session(self):
        """On a normal trading day before 18:30 IST, EOD is not published yet; must resolve to prior trading session."""
        # 2026-10-07 (Wednesday) at 14:00 IST (08:30 UTC)
        ref_dt = datetime.datetime(2026, 10, 7, 8, 30, tzinfo=datetime.timezone.utc)
        expected = get_expected_latest_eod(ref_dt)
        self.assertEqual(expected, "2026-10-06", "Before 18:30 IST on Wednesday must resolve to Tuesday EOD.")

    def test_02_evening_trading_day_resolves_to_today(self):
        """On a normal trading day after 18:30 IST, bhavcopy is published; must resolve to TODAY."""
        # 2026-10-07 (Wednesday) at 19:15 IST (13:45 UTC)
        ref_dt = datetime.datetime(2026, 10, 7, 13, 45, tzinfo=datetime.timezone.utc)
        expected = get_expected_latest_eod(ref_dt)
        self.assertEqual(expected, "2026-10-07", "After 18:30 IST on Wednesday must resolve to Wednesday EOD.")

    def test_03_weekend_saturday_and_sunday_resolves_to_friday(self):
        """On weekends, market is closed; must resolve to preceding Friday session in calendar."""
        # Saturday 2026-10-10 at 12:00 UTC
        sat_dt = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(sat_dt), "2026-10-09")

        # Sunday 2026-10-11 at 18:00 UTC
        sun_dt = datetime.datetime(2026, 10, 11, 18, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(sun_dt), "2026-10-09")

    def test_04_statutory_holiday_resolves_to_preceding_session(self):
        """Statutory exchange holiday (e.g. 2026-10-02 Mahatma Gandhi Jayanti) must resolve to prior trading session."""
        # 2026-10-02 at 20:00 IST
        holiday_dt = datetime.datetime(2026, 10, 2, 14, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(holiday_dt), "2026-10-01")

        # Monday morning following holiday weekend (2026-10-05 at 10:00 IST)
        mon_am_dt = datetime.datetime(2026, 10, 5, 4, 30, tzinfo=datetime.timezone.utc)
        self.assertEqual(get_expected_latest_eod(mon_am_dt), "2026-10-01")

    def test_05_scanner_unspecified_date_stale_detection_fails_closed(self):
        """Scanner called with as_of_date=None must detect database is stale and fail-closed when allow_stale=False."""
        scanner = PydroidScanner(BASE_DIR)
        # Mock get_expected_latest_eod to simulate that a newer session has completed
        with patch("core.scanner.get_expected_latest_eod", return_value="2099-12-31"), \
             patch("core.data_engine.get_expected_latest_eod", return_value="2099-12-31"):
            with self.assertRaises(StaleDataError) as ctx:
                scanner.run_scan(as_of_date=None, auto_update_universe=False, allow_stale_data=False)
            self.assertIn("CRITICAL: LATEST MARKET DATA UNAVAILABLE", str(ctx.exception))
            self.assertIn("2099-12-31", str(ctx.exception))

    def test_06_scanner_unspecified_date_allow_stale_succeeds_with_warning(self):
        """Scanner called with allow_stale_data=True proceeds on available database date when future date expected."""
        ok, res_date, diag = resolve_latest_valid_eod(as_of_date=None, allow_stale=True)
        self.assertTrue(ok)
        self.assertEqual(res_date, get_latest_date())
        self.assertIn("status", diag)

    def test_07_explicit_historical_date_bypasses_future_freshness(self):
        """When an explicit valid historical date is requested, it validates and returns that exact date."""
        ok, res_date, diag = resolve_latest_valid_eod(as_of_date="2026-08-31")
        self.assertTrue(ok)
        self.assertEqual(res_date, "2026-08-31")
        self.assertEqual(diag["status"], "EXPLICIT_DATE_VALIDATED")


if __name__ == "__main__":
    unittest.main()
