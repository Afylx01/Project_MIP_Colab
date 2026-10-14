"""
MIP Android — Scheduler & Alert Dispatcher Contract Tests
Phase 42: TDD contract test suite for crontab generator, daemon scheduling, alert formatting, and bounded log rotation.
"""

import os
import sys
import json
import logging
from logging.handlers import RotatingFileHandler
import shutil
import tempfile
import unittest
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_production_pipeline import (
    HeadlessProductionPipeline,
    LockAcquisitionError,
)
from scripts.schedule_production_cron import (
    ProductionScheduler,
    setup_scheduler_logging,
)
from scripts.alert_dispatcher import AlertDispatcher


class TestSchedulerAndAlerts(unittest.TestCase):
    """Verifies scheduler daemon calculations, alert formatting, exception hierarchies, and log rotation."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_sched_test_"))
        self.reports_dir = self.temp_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.csv_path = PROJECT_ROOT / "reports" / "screener_output_live.csv"
        self.csv_backup = None
        if self.csv_path.exists():
            self.csv_backup = self.csv_path.read_bytes()

    def tearDown(self):
        if self.csv_backup is not None:
            self.csv_path.write_bytes(self.csv_backup)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_lock_acquisition_error_is_blocking_io_error(self):
        """Verifies LockAcquisitionError inherits from BlockingIOError for standard POSIX concurrency handling."""
        err = LockAcquisitionError("Test concurrent lock rejection")
        self.assertIsInstance(err, BlockingIOError)
        self.assertIsInstance(err, OSError)

    @patch("scripts.run_production_pipeline.HardenedScanner")
    def test_breadth_and_sector_json_deliverables_created(self, mock_scanner_cls):
        """Verifies market_breadth.json and sector_rotation.json are serialized upon scan execution (COND-41-01)."""
        mock_scanner = MagicMock()
        mock_scanner_cls.return_value = mock_scanner
        from core.config import MIPScannerConfig
        mock_scanner.config = MIPScannerConfig()

        mock_df = pd.DataFrame([{"symbol": "SBIN", "signal_type": "BEAR_HOLD", "rank": 1, "sector": "Financial Services"}])
        mock_df.attrs["breadth_results"] = {"advance_decline_ratio": 1.5, "regime": "BULL"}
        mock_df.attrs["sector_results"] = {"top_sector": "NIFTY_BANK"}
        mock_df.attrs["universe_label"] = "NIFTY Bank"
        mock_scanner.run_hardened_scan.return_value = (mock_df, {"Current": 14}, {}, {})

        pipeline = HeadlessProductionPipeline(base_dir=PROJECT_ROOT)
        pipeline.reports_dir = self.reports_dir
        pipeline.telemetry_path = self.reports_dir / "pipeline_telemetry.json"

        telemetry = pipeline.run_pipeline(
            universe="NIFTY Bank",
            force_refresh=False,
            allow_stale=True,
            skip_health_check=True,
            dispatch_alert=False,
        )

        breadth_file = self.reports_dir / "market_breadth.json"
        sector_file = self.reports_dir / "sector_rotation.json"

        self.assertTrue(breadth_file.exists(), f"market_breadth.json missing at {breadth_file}")
        self.assertTrue(sector_file.exists(), f"sector_rotation.json missing at {sector_file}")

        # Check JSON parseability
        breadth_data = json.loads(breadth_file.read_text(encoding="utf-8"))
        sector_data = json.loads(sector_file.read_text(encoding="utf-8"))

        self.assertIsInstance(breadth_data, dict)
        self.assertIsInstance(sector_data, dict)
        self.assertIn("market_breadth", telemetry["deliverables"])
        self.assertIn("sector_rotation", telemetry["deliverables"])

    def test_cron_daemon_schedule_calculation(self):
        """Verifies next market close calculation correctly identifies 18:30 IST on trading days."""
        scheduler = ProductionScheduler(base_dir=PROJECT_ROOT)

        # Test on a known past trading session morning (e.g. 2026-10-09 06:00 UTC = 11:30 IST)
        dt_morning = datetime.datetime(2026, 10, 9, 6, 0, 0, tzinfo=datetime.timezone.utc)
        next_close = scheduler.get_next_market_close(dt_morning)

        # 18:30 IST = 13:00 UTC
        expected_close = datetime.datetime(2026, 10, 9, 13, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(next_close, expected_close)

        # Test on a known past trading session after close (e.g. 2026-10-09 14:00 UTC = 19:30 IST)
        # Next trading day in calendar after 2026-10-09 is 2026-10-12 (Monday)
        dt_evening = datetime.datetime(2026, 10, 9, 14, 0, 0, tzinfo=datetime.timezone.utc)
        next_close_after = scheduler.get_next_market_close(dt_evening)
        expected_next = datetime.datetime(2026, 10, 12, 13, 0, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(next_close_after, expected_next)

    def test_crontab_entry_generation(self):
        """Verifies crontab configuration line format and binary path inclusion."""
        scheduler = ProductionScheduler(base_dir=PROJECT_ROOT)
        entry = scheduler.generate_crontab_entry(python_bin="/usr/bin/python3")

        self.assertIn("30 18 * * 1-5", entry)
        self.assertIn("/usr/bin/python3", entry)
        self.assertIn("scripts/run_production_pipeline.py", entry)
        self.assertIn("logs/production_pipeline.log", entry)

    def test_log_rotation_configuration(self):
        """Verifies RotatingFileHandler is initialized with bounded size (10 MB, 5 backups)."""
        log_dir = self.temp_dir / "logs"
        logger = setup_scheduler_logging(
            log_dir=log_dir,
            log_filename="test_sched.log",
            logger_name="TestSchedLogger",
        )

        rotating_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
        self.assertGreater(len(rotating_handlers), 0)
        h = rotating_handlers[0]
        self.assertEqual(h.maxBytes, 10 * 1024 * 1024)
        self.assertEqual(h.backupCount, 5)

        logger.info("Test log line for rotation verification.")
        self.assertTrue((log_dir / "test_sched.log").exists())

    def test_alert_dispatcher_payload_formatting(self):
        """Verifies formatted notification string contains top candidates, sector caps, and regime state."""
        dispatcher = AlertDispatcher(base_dir=PROJECT_ROOT)
        payload = dispatcher.format_alert_payload()

        self.assertIn("Project MIP Momentum Scanner Alert", payload)
        self.assertIn("Operational Health", payload)
        self.assertIn("Market Regime", payload)
        self.assertIn("Top Momentum Candidates", payload)

    def test_alert_dispatcher_offline_fail_safe(self):
        """Verifies dispatch fails safely without halting the pipeline when unconfigured or offline."""
        dispatcher = AlertDispatcher(base_dir=PROJECT_ROOT)
        dispatcher.dispatch_log_path = self.reports_dir / "alert_dispatch.json"

        # Mock unconfigured state
        with patch.object(dispatcher.telegram_sender, "is_configured", return_value=False):
            record = dispatcher.dispatch(dry_run=False)
            self.assertEqual(record["status"], "SKIPPED_UNCONFIGURED")
            self.assertTrue(dispatcher.dispatch_log_path.exists())

        # Test dry-run mode
        record_dry = dispatcher.dispatch(dry_run=True)
        self.assertEqual(record_dry["status"], "DRY_RUN_SUCCESS")

        # Test network exception safety
        with patch.object(dispatcher.telegram_sender, "is_configured", return_value=True), \
             patch.object(dispatcher.telegram_sender, "send_message", side_effect=ConnectionError("Mock network down")):
            record_err = dispatcher.dispatch(dry_run=False)
            self.assertEqual(record_err["status"], "OFFLINE_FAILED")
            self.assertIn("Mock network down", record_err["message"])


if __name__ == "__main__":
    unittest.main()
