import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import unittest
import pandas as pd
from core.scanner import PydroidScanner, format_screener_tearsheet
from core.telegram_sender import format_telegram_alert
from scripts.scanner_hardening import HardenedScanner


class TestScannerDatabaseAuditAndAutoDownload(unittest.TestCase):
    """Verifies database synchronization audit, auto-download excel support, and NIFTY750 defaults."""

    def setUp(self):
        self.base_dir = Path(__file__).resolve().parent.parent

    def test_tearsheet_database_audit_formatting_updated(self):
        """format_screener_tearsheet must include section [0] DATABASE SYNCHRONIZATION AUDIT when updated."""
        dummy_top = pd.DataFrame([{
            "symbol": "TCS", "close": 3500.0, "rank": 1, "sector": "IT",
            "volar_score": 85.0, "ret_1y": 25.0, "rrg_quadrant": "Leading", "stop_loss": 3300.0
        }])
        dummy_top.attrs["universe_label"] = "NIFTY 750"
        dummy_top.attrs["db_audit"] = {
            "is_updated": True,
            "pre_latest_date": "2026-10-09",
            "post_latest_date": "2026-10-14",
            "pre_row_count": 2164420,
            "post_row_count": 2167514,
            "new_rows_added": 3094,
            "gdrive_backed_up": True,
        }

        tearsheet = format_screener_tearsheet(
            top_df=dummy_top,
            breadth={"universe_size": 750},
            sectors={"sectors": []},
            regime={"label": "BULL_NORMAL"},
            as_of_date="2026-10-14",
            universe_label="NIFTY 750",
        )

        self.assertIn("[0] DATABASE SYNCHRONIZATION AUDIT", tearsheet)
        self.assertIn("UPDATED (Fresh market bars acquired)", tearsheet)
        self.assertIn("+3,094 rows committed to SQLite", tearsheet)
        self.assertIn("2026-10-09 ➔ 2026-10-14", tearsheet)
        self.assertIn("Backup completed to /MyDrive/MIP/universe.db", tearsheet)

    def test_tearsheet_database_audit_formatting_uptodate(self):
        """format_screener_tearsheet must report verified up to date when no new rows added."""
        dummy_top = pd.DataFrame([{
            "symbol": "INFY", "close": 1800.0, "rank": 1, "sector": "IT",
            "volar_score": 82.0, "ret_1y": 20.0, "rrg_quadrant": "Leading", "stop_loss": 1700.0
        }])
        dummy_top.attrs["universe_label"] = "NIFTY 750"
        dummy_top.attrs["db_audit"] = {
            "is_updated": False,
            "pre_latest_date": "2026-10-14",
            "post_latest_date": "2026-10-14",
            "pre_row_count": 2167514,
            "post_row_count": 2167514,
            "new_rows_added": 0,
            "gdrive_backed_up": False,
        }

        tearsheet = format_screener_tearsheet(
            top_df=dummy_top,
            breadth={"universe_size": 750},
            sectors={"sectors": []},
            regime={"label": "BULL_NORMAL"},
            as_of_date="2026-10-14",
            universe_label="NIFTY 750",
        )

        self.assertIn("[0] DATABASE SYNCHRONIZATION AUDIT", tearsheet)
        self.assertIn("VERIFIED UP-TO-DATE", tearsheet)
        self.assertIn("2,167,514 rows in prices table", tearsheet)

    def test_telegram_alert_database_status(self):
        """format_telegram_alert must display database update status line."""
        dummy_top = pd.DataFrame([{
            "symbol": "RELIANCE", "close": 2800.0, "rank": 1, "volar_score": 90.0, "ret_1y": 30.0
        }])
        db_audit = {
            "is_updated": True,
            "pre_latest_date": "2026-10-09",
            "post_latest_date": "2026-10-14",
            "new_rows_added": 3094,
            "post_row_count": 2167514,
            "gdrive_backed_up": True,
        }

        alert = format_telegram_alert(
            top_df=dummy_top,
            breadth={"universe_size": 750},
            sectors={"sectors": []},
            regime={"label": "BULL_NORMAL"},
            as_of_date="2026-10-14",
            universe_label="NIFTY 750",
            db_audit=db_audit,
        )

        self.assertIn("Database:", alert)
        self.assertIn("Updated (+3,094 rows ➔ <code>2026-10-14</code> | ☁️ Drive Synced)", alert)

    def test_scanner_signatures_support_auto_download_excel(self):
        """Both PydroidScanner and HardenedScanner must accept auto_download_excel in run_scan."""
        import inspect
        sig_base = inspect.signature(PydroidScanner.run_scan)
        self.assertIn("auto_download_excel", sig_base.parameters)
        self.assertFalse(sig_base.parameters["auto_download_excel"].default)

        sig_hardened = inspect.signature(HardenedScanner.run_scan)
        self.assertIn("auto_download_excel", sig_hardened.parameters)
        self.assertFalse(sig_hardened.parameters["auto_download_excel"].default)

    def test_trigger_colab_download_deduplication_and_cooldown(self):
        """trigger_colab_download must strictly deduplicate repeated downloads within cooldown period."""
        from unittest.mock import MagicMock, patch
        from scripts.scanner_hardening import trigger_colab_download, _COLAB_DOWNLOAD_REGISTRY
        import time

        test_path = "/tmp/test_report.xlsx"
        _COLAB_DOWNLOAD_REGISTRY.clear()

        mock_files = MagicMock()
        with patch.dict("sys.modules", {"google.colab": MagicMock(files=mock_files)}):
            # First call -> Must trigger download
            first_res = trigger_colab_download(test_path, cooldown_seconds=2.0)
            self.assertTrue(first_res)
            mock_files.download.assert_called_once_with(test_path)

            # Second call within 2.0s cooldown -> Must be ignored/deduplicated
            second_res = trigger_colab_download(test_path, cooldown_seconds=2.0)
            self.assertFalse(second_res)
            # Call count should STILL be 1 (zero duplicates!)
            mock_files.download.assert_called_once()

            # Different file -> Must trigger download
            other_path = "/tmp/other_report.xlsx"
            other_res = trigger_colab_download(other_path, cooldown_seconds=2.0)
            self.assertTrue(other_res)
            self.assertEqual(mock_files.download.call_count, 2)

            # Calling with empty/None -> returns False safely
            self.assertFalse(trigger_colab_download(None))
            self.assertFalse(trigger_colab_download(""))


if __name__ == "__main__":
    unittest.main()

