"""
MIP Android — End-to-End Operational Orchestrator Contract Tests
Phase 43: TDD contract test suite for unified pipeline alert chaining,
calendar-aware crontab generation, holiday handling, and critical health alerting.
"""

import os
import sys
import json
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

from core.config import MIPScannerConfig
from scripts.run_production_pipeline import (
    HeadlessProductionPipeline,
    LockAcquisitionError,
)
from scripts.schedule_production_cron import ProductionScheduler
from scripts.alert_dispatcher import AlertDispatcher


class TestEndToEndOperationalOrchestrator(unittest.TestCase):
    """Verifies pipeline alert chaining, calendar crontab modes, holiday guards, and critical health alerts."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_e2e_orch_test_"))
        self.reports_dir = self.temp_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("scripts.run_production_pipeline.HardenedScanner")
    def test_pipeline_automatically_invokes_alert_dispatcher(self, mock_scanner_cls):
        """Asserts pipeline.run_pipeline(dispatch_alert=True) dispatches alert and records deliverable."""
        mock_scanner = MagicMock()
        mock_scanner_cls.return_value = mock_scanner
        mock_scanner.config = MIPScannerConfig()

        mock_df = pd.DataFrame([{"symbol": "TCS", "signal_type": "BEAR_HOLD", "rank": 1, "sector": "Information Technology"}])
        mock_df.attrs["breadth_results"] = {"advance_decline_ratio": 1.2, "regime": "NEUTRAL"}
        mock_df.attrs["sector_results"] = {"top_sector": "IT"}
        mock_df.attrs["universe_label"] = "NIFTY 500"
        mock_scanner.run_hardened_scan.return_value = (mock_df, {"Current": 500}, {}, {})

        pipeline = HeadlessProductionPipeline(base_dir=PROJECT_ROOT)
        pipeline.reports_dir = self.reports_dir
        pipeline.telemetry_path = self.reports_dir / "pipeline_telemetry.json"

        # Run pipeline with dispatch_alert=True and dry_run=True to isolate network calls
        telemetry = pipeline.run_pipeline(
            universe="NIFTY500",
            force_refresh=False,
            allow_stale=True,
            skip_health_check=True,
            dispatch_alert=True,
            dry_run=True,
        )

        self.assertEqual(telemetry["pipeline_status"], "SUCCESS")
        self.assertEqual(telemetry["alert_dispatch_status"], "DRY_RUN_SUCCESS")
        self.assertIn("alert_dispatch", telemetry["deliverables"])
        self.assertTrue(Path(telemetry["deliverables"]["alert_dispatch"]).exists())

        # Inspect alert dispatch log
        dispatch_log = json.loads(Path(telemetry["deliverables"]["alert_dispatch"]).read_text(encoding="utf-8"))
        self.assertEqual(dispatch_log["status"], "DRY_RUN_SUCCESS")
        self.assertTrue(dispatch_log["dry_run"])

    @patch("scripts.run_production_pipeline.HardenedScanner")
    def test_pipeline_alert_dispatch_failure_does_not_abort_scan(self, mock_scanner_cls):
        """Verifies network/credentials exception in alert dispatcher does not alter pipeline_status: SUCCESS."""
        mock_scanner = MagicMock()
        mock_scanner_cls.return_value = mock_scanner
        mock_scanner.config = MIPScannerConfig()

        mock_df = pd.DataFrame([{"symbol": "INFY", "signal_type": "BEAR_HOLD", "rank": 1, "sector": "Information Technology"}])
        mock_df.attrs["breadth_results"] = {"advance_decline_ratio": 1.1, "regime": "NEUTRAL"}
        mock_df.attrs["sector_results"] = {"top_sector": "IT"}
        mock_df.attrs["universe_label"] = "NIFTY 500"
        mock_scanner.run_hardened_scan.return_value = (mock_df, {"Current": 500}, {}, {})

        pipeline = HeadlessProductionPipeline(base_dir=PROJECT_ROOT)
        pipeline.reports_dir = self.reports_dir
        pipeline.telemetry_path = self.reports_dir / "pipeline_telemetry.json"

        # Mock AlertDispatcher.dispatch to throw exception
        with patch.object(AlertDispatcher, "dispatch", side_effect=ConnectionError("Simulated Telegram gateway failure")):
            telemetry = pipeline.run_pipeline(
                universe="NIFTY500",
                force_refresh=False,
                allow_stale=True,
                skip_health_check=True,
                dispatch_alert=True,
            )

        self.assertEqual(telemetry["pipeline_status"], "SUCCESS")
        self.assertEqual(telemetry["alert_dispatch_status"], "EXCEPTION")
        self.assertEqual(telemetry["deliverables"]["alert_dispatch"], "")

    def test_crontab_generator_daemon_step_mode(self):
        """Asserts crontab entry generated with mode='daemon_step' targets schedule_production_cron.py --once."""
        scheduler = ProductionScheduler(base_dir=PROJECT_ROOT)

        # 1. Daemon step mode
        entry_daemon = scheduler.generate_crontab_entry(
            python_bin="/usr/bin/python3",
            mode="daemon_step",
        )
        self.assertIn("30 18 * * 1-5", entry_daemon)
        self.assertIn("/usr/bin/python3", entry_daemon)
        self.assertIn("scripts/schedule_production_cron.py", entry_daemon)
        self.assertIn("--once", entry_daemon)
        self.assertIn("logs/scheduler_daemon.log", entry_daemon)

        # 2. Direct pipeline mode
        entry_pipeline = scheduler.generate_crontab_entry(
            python_bin="/usr/bin/python3",
            mode="pipeline",
        )
        self.assertIn("30 18 * * 1-5", entry_pipeline)
        self.assertIn("/usr/bin/python3", entry_pipeline)
        self.assertIn("scripts/run_production_pipeline.py", entry_pipeline)
        self.assertIn("logs/production_pipeline.log", entry_pipeline)

    def test_daemon_step_on_holiday_exits_cleanly(self):
        """Validates execution on known NSE holidays (e.g. 2026-01-26 Republic Day) exits with action_taken: IDLE."""
        scheduler = ProductionScheduler(base_dir=PROJECT_ROOT)

        # 2026-01-26 is Republic Day (official NSE weekday trading holiday)
        # 18:30 IST = 13:00 UTC
        republic_day_utc = datetime.datetime(2026, 1, 26, 13, 0, 0, tzinfo=datetime.timezone.utc)

        res = scheduler.run_daemon_step(
            universe="NIFTY750",
            dry_run=True,
            now_utc=republic_day_utc,
        )

        self.assertEqual(res["today"], "2026-01-26")
        self.assertFalse(res["is_trading_day"])
        self.assertEqual(res["action_taken"], "IDLE")
        self.assertEqual(res["reason"], "NON_TRADING_DAY")

    def test_critical_health_failure_alert_formatting(self):
        """Asserts formatting of critical health alert payload on simulated pre-flight failure."""
        dispatcher = AlertDispatcher(base_dir=PROJECT_ROOT)
        dispatcher.dispatch_log_path = self.reports_dir / "alert_dispatch.json"

        health_summary = {
            "overall_health": "UNHEALTHY",
            "checks_passed": 5,
            "checks_total": 7,
            "failed_checks": [
                "Corporate Actions Hash Check (Mismatch)",
                "Strategy Fingerprint Invariant (Altered)",
            ],
        }

        # Format message
        payload = dispatcher.format_critical_health_alert(health_summary)
        self.assertIn("🚨 <b>CRITICAL OPERATIONAL ALERT: Health Check Failed</b>", payload)
        self.assertIn("UNHEALTHY", payload)
        self.assertIn("5/7 checks passed", payload)
        self.assertIn("Corporate Actions Hash Check (Mismatch)", payload)
        self.assertIn("Strategy Fingerprint Invariant (Altered)", payload)
        self.assertIn("Downstream momentum scan halted", payload)

        # Test dispatch in dry run
        record = dispatcher.dispatch_health_failure(health_summary, dry_run=True)
        self.assertEqual(record["type"], "CRITICAL_HEALTH_FAILURE")
        self.assertEqual(record["status"], "DRY_RUN_SUCCESS")
        self.assertTrue(dispatcher.dispatch_log_path.exists())


if __name__ == "__main__":
    unittest.main()
