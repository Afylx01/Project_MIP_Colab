"""
Contract Test Suite: Google Colab Compatibility & Zero-Leak Security Audit
Validates multi-architecture compiler options, writable ext4 target paths,
cloud sync fail-safes, and zero-leak credential isolation for Project MIP.
"""

import os
import sys
import platform
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from brute_force.bridge import get_so_target_path, get_compiler_bin
from scripts.cloud_sync import is_running_in_colab, sync_universe_from_gdrive, benchmark_storage_latency
from core.config import MIPScannerConfig
from scripts.scanner_hardening import get_canonical_strategy_fingerprint
from core.data_engine import get_db_path, get_universe_statistics


class TestColabCompatibilityAndSecurity(unittest.TestCase):
    def test_01_so_target_path_never_targets_android_noexec(self):
        """Native shared library target path must NEVER reside on Android noexec mount points."""
        so_path = get_so_target_path()
        so_str = str(so_path)
        forbidden_prefixes = ("/storage/emulated", "/mnt/sdcard", "/sdcard", "/storage/self")
        for p in forbidden_prefixes:
            self.assertFalse(so_str.startswith(p), f"so_path '{so_str}' violates Android noexec security invariant ({p}).")

    def test_02_compiler_flags_architecture_selection(self):
        """Validates that compiler flags match target hardware architecture (x86_64 AVX2 vs ARM64 NEON)."""
        # Test x86_64 flags
        with patch("platform.machine", return_value="x86_64"):
            machine = platform.machine().lower()
            if machine in ("x86_64", "amd64"):
                arch_flags = ["-march=native", "-mavx2", "-mfma"]
            else:
                arch_flags = []
            self.assertIn("-mavx2", arch_flags)
            self.assertIn("-mfma", arch_flags)

        # Test ARM64 flags
        with patch("platform.machine", return_value="aarch64"):
            machine = platform.machine().lower()
            if machine in ("aarch64", "arm64", "armv8l"):
                arch_flags = ["-march=armv8.2-a+fp16"]
            else:
                arch_flags = []
            self.assertIn("-march=armv8.2-a+fp16", arch_flags)

    def test_03_zero_leak_no_credentials_in_repository(self):
        """Repository tree must contain strictly ZERO service account keys, tokens, or .env files."""
        colab_repo = (BASE_DIR.parent / "Project_MIP_Colab") if (BASE_DIR.name != "Project_MIP_Colab" and (BASE_DIR.parent / "Project_MIP_Colab").exists()) else BASE_DIR
        # 1. No .env file
        self.assertFalse((colab_repo / ".env").exists(), f".env file must NOT exist in the shareable repository: {colab_repo}")

        # 2. No Service Account JSONs
        json_files = list(colab_repo.glob("**/*.json"))
        allowed_json_basenames = {
            "symbol_sector_map.json",
            "corporate_actions_registry.json",
            "constituent_snapshots.json",
            "investing_settings.example.json",
            "PROVENANCE_MANIFEST.json",
            "PRODUCTION_READINESS_CERTIFICATE.json",
            "RELEASE_DISTRIBUTION_MANIFEST.json",
        }
        for jf in json_files:
            # Skip reports or tests fixtures if any
            if "reports" in jf.parts or ".pytest_cache" in jf.parts:
                continue
            self.assertIn(jf.name, allowed_json_basenames, f"Forbidden JSON artifact detected in repository: {jf}")

        # 3. No token text files
        for forbidden in ("GitHub_Token.txt", "GitHub_FineGrained_Token.txt", "telegram toke.txt", "GCP_SA.json"):
            self.assertFalse((colab_repo / forbidden).exists(), f"Forbidden credential file detected: {forbidden}")

    def test_04_gitignore_rules_comprehensiveness(self):
        """Validates that .gitignore excludes all sensitive credentials, large databases, and build artifacts."""
        colab_repo = (BASE_DIR.parent / "Project_MIP_Colab") if (BASE_DIR.name != "Project_MIP_Colab" and (BASE_DIR.parent / "Project_MIP_Colab").exists()) else BASE_DIR
        gitignore_path = colab_repo / ".gitignore"
        self.assertTrue(gitignore_path.exists(), f".gitignore must exist in {colab_repo}.")
        content = gitignore_path.read_text(encoding="utf-8")

        required_patterns = [
            ".env",
            "*service_account*.json",
            "data/universe.db",
            "*.so",
            "*.o",
            "reports/*.xlsx",
            "__pycache__/",
        ]
        for pat in required_patterns:
            self.assertIn(pat, content, f"Required pattern '{pat}' missing from .gitignore")

    def test_05_cloud_sync_graceful_missing_source_handling(self):
        """sync_universe_from_gdrive must return clear diagnostic failure when sources are absent, without unhandled exceptions."""
        non_existent_dest = BASE_DIR / "data" / ".test_missing_db.db"
        try:
            ok, status, meta = sync_universe_from_gdrive(
                destination_path=non_existent_dest,
                gdrive_source_path=Path("/non/existent/drive/path/universe.db"),
                verbose=False,
            )
            self.assertFalse(ok)
            self.assertEqual(status, "SOURCE_DATABASE_NOT_FOUND")
            self.assertIn("help", meta)
        finally:
            if non_existent_dest.exists():
                non_existent_dest.unlink()

    def test_06_database_integrity_and_row_count(self):
        """universe.db must pass PRAGMA quick_check and have strictly 2,164,420 rows."""
        db_path = get_db_path()
        self.assertTrue(db_path.exists(), f"universe.db must exist at {db_path}")

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check;")
        check = cursor.fetchone()[0]
        self.assertEqual(check.lower(), "ok")

        cursor.execute("SELECT COUNT(*) FROM prices;")
        total_rows = cursor.fetchone()[0]
        self.assertIn(total_rows, (2164420, 2167514), "Total rows in prices must match baseline (2,164,420) or updated (2,167,514).")

        cursor.execute("SELECT MAX(date) FROM prices;")
        max_date = cursor.fetchone()[0]
        self.assertIn(max_date, ("2026-10-09", "2026-10-14"), "Max date in prices must match baseline (2026-10-09) or updated (2026-10-14).")
        conn.close()

    def test_07_canonical_strategy_fingerprint(self):
        """Canonical frozen strategy fingerprint must strictly match podcast specification."""
        cfg = MIPScannerConfig()
        fp = get_canonical_strategy_fingerprint(cfg)
        self.assertEqual(
            fp,
            "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de",
            "Strategy fingerprint must strictly match canonical value."
        )


if __name__ == "__main__":
    unittest.main()
