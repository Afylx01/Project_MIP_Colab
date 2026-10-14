"""
TDD Security Hardening & OWASP Top 10 Safeguard Verification Suite.

Validates institutional defenses against:
- OWASP A02: Cryptographic Failures & Sensitive Information Exposure (CWE-209, CWE-532)
- OWASP A03: Injection Attacks & Shell Command Execution (CWE-78)
- OWASP A05: Security Misconfiguration & Uncontrolled Resource Consumption (CWE-400, CWE-409)
- OWASP A01: Broken Access Control & Insecure File Permissions (CWE-732)
- Input Validation & Path Traversal Guards (CWE-20)
"""

import inspect
import io
import os
import re
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure root workspace is on sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


class TestOWASPA02TelegramTokenSanitization(unittest.TestCase):
    """OWASP A02/A09: Sensitive token redaction in exception messages and logs."""

    def test_sanitize_error_redacts_bot_token(self):
        from core.telegram_sender import TelegramSender

        fake_token = "7891234567:AAHxyz_SecretBotToken_9876543210"
        sender = TelegramSender(bot_token=fake_token, chat_id="123456789")

        # Must provide _sanitize_error method
        self.assertTrue(hasattr(sender, "_sanitize_error"), "TelegramSender must implement _sanitize_error()")

        leaked_err_msg = (
            f"HTTPError: 404 Client Error for url: "
            f"https://api.telegram.org/bot{fake_token}/sendMessage"
        )
        sanitized = sender._sanitize_error(leaked_err_msg)

        self.assertNotIn(fake_token, sanitized)
        self.assertIn("[REDACTED_BOT_TOKEN]", sanitized)

    def test_send_message_exception_does_not_leak_token(self):
        from core.telegram_sender import TelegramSender

        fake_token = "7891234567:AAHxyz_SecretBotToken_9876543210"
        sender = TelegramSender(bot_token=fake_token, chat_id="123456789")

        # Simulate exception during request
        with patch.object(sender, "_get_session", return_value=None):
            with patch("urllib.request.urlopen", side_effect=Exception(f"Connection failed to https://api.telegram.org/bot{fake_token}/sendMessage")):
                with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                    success = sender.send_message("Test message")
                    output = mock_stdout.getvalue()

                self.assertFalse(success)
                self.assertNotIn(fake_token, output, "Raw bot token leaked into stdout exception trace!")
                self.assertIn("[REDACTED_BOT_TOKEN]", output)


class TestOWASPA03CommandInjectionGuard(unittest.TestCase):
    """OWASP A03: Shell interpolation and command injection prevention."""

    def test_main_py_uses_subprocess_not_os_system(self):
        main_py = BASE_DIR / "main.py"
        content = main_py.read_text(encoding="utf-8")

        # os.system with sys.executable string interpolation is prohibited
        self.assertNotIn(
            'os.system(f\'"{sys.executable}"',
            content,
            "main.py must not use os.system with interpolated sys.executable; use subprocess.run instead."
        )

        # Must invoke subprocess.run
        self.assertIn("subprocess.run([sys.executable", content)


class TestOWASPA05UnboundedResourceGuards(unittest.TestCase):
    """OWASP A05: Bounded timeouts, zip decompression limits, and buffer boundaries."""

    def test_sync_sectors_urllib_has_explicit_timeout_and_bounded_read(self):
        sync_sectors_py = BASE_DIR / "core" / "sync_sectors.py"
        content = sync_sectors_py.read_text(encoding="utf-8")

        # urllib.request.urlopen must specify timeout
        self.assertNotIn(
            "with urllib.request.urlopen(req) as response:",
            content,
            "urllib.request.urlopen in sync_sectors.py must have an explicit timeout parameter!"
        )

        # response.read must be bounded
        self.assertNotIn(
            "csv_path.write_bytes(response.read())",
            content,
            "response.read() in sync_sectors.py must be bounded to prevent unbounded memory allocation!"
        )

    def test_auto_fetch_zip_guards_empty_archive_and_size_bounds(self):
        from core.auto_fetch import PydroidAutoFetch

        engine = PydroidAutoFetch()

        # Create an empty zip file with 0 csv files
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as z:
            z.writestr("notes.txt", "No csv here")
        zip_bytes = zip_buf.getvalue()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = zip_bytes

        mock_session = MagicMock()
        mock_session.get.return_value = mock_resp

        with patch.object(engine, "_get_session", return_value=mock_session):
            # Must handle empty zip gracefully without crashing with unhandled IndexError
            res = engine.fetch_bhavcopy_for_date("2026-10-09")
            self.assertIsNone(res)

    def test_scanner_hardening_fetch_official_csv_bounded_read(self):
        scanner_hardening_py = BASE_DIR / "scripts" / "scanner_hardening.py"
        content = scanner_hardening_py.read_text(encoding="utf-8")

        self.assertNotIn(
            "data = resp.read()\n",
            content,
            "resp.read() in scanner_hardening.py fetch_official_csv must have a buffer size limit!"
        )


class TestOWASPA01FilePermissionsAndInputValidation(unittest.TestCase):
    """OWASP A01: Broken Access Control & Input Validation."""

    def test_save_investing_settings_enforces_restrictive_permissions(self):
        if os.name != "posix":
            self.skipTest("File permission test requires POSIX filesystem")

        from core.settings import save_investing_settings, DEFAULT_INVESTING_SETTINGS

        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            settings_file = tmppath / "data" / "investing_settings.json"

            success = save_investing_settings(dict(DEFAULT_INVESTING_SETTINGS), base_dir=tmppath)
            self.assertTrue(success)
            self.assertTrue(settings_file.exists())

            # Check permissions: must be 0o600 (-rw-------)
            file_mode = stat.S_IMODE(settings_file.stat().st_mode)
            self.assertEqual(
                file_mode,
                0o600,
                f"Settings file permissions must be 0o600, got octal {oct(file_mode)}"
            )

    def test_cloud_sync_validates_google_drive_file_id(self):
        from scripts.cloud_sync import validate_gdrive_file_id

        # Valid Google Drive File IDs
        valid_id = "1a2B3c4D5e6F7g8H9i0J_kLmNoPqRsTuVw-XyZ"
        self.assertTrue(validate_gdrive_file_id(valid_id))

        # Adversarial / Invalid File IDs (Path Traversal, Injection, Length)
        invalid_ids = [
            "../../etc/passwd",
            "file_id;rm -rf /",
            "id&token=12345",
            "short",
            "a" * 150,  # too long
            "",
            None,
            "bad file id with spaces",
            "id_with_newline\n",
        ]
        for bad_id in invalid_ids:
            self.assertFalse(
                validate_gdrive_file_id(bad_id),
                f"Malicious or invalid file ID '{bad_id}' was not rejected!"
            )


if __name__ == "__main__":
    unittest.main()
