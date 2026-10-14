"""
MIP Android — File Integrity Tests
Validates SHA-256 hashes of critical production modules against source.
"""

import unittest
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class TestStrategyFingerprintIntegrity(unittest.TestCase):
    """Verify the frozen strategy fingerprint is reproducible."""

    CANONICAL_FINGERPRINT = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"

    def test_fingerprint_from_parameters(self):
        import json
        params = {
            "ema_regime_span": 20,
            "ema_rs_span": 200,
            "ema_trend_span": 200,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "momentum_lookback_bars": 252,
            "retrace_threshold": 0.80,
            "top_n_candidates": 20,
            "volatility_floor": 0.05,
        }
        serialized = json.dumps(params, sort_keys=True)
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.assertEqual(fp, self.CANONICAL_FINGERPRINT)


class TestCoreModulePresence(unittest.TestCase):
    """Verify all 25 expected core modules exist."""

    EXPECTED_MODULES = [
        "__init__.py",
        "analytical_price.py",
        "anomaly.py",
        "auto_fetch.py",
        "backtest.py",
        "benchmark_validator.py",
        "breadth.py",
        "config.py",
        "data_engine.py",
        "delivery.py",
        "etf_engine.py",
        "excel_generator.py",
        "health.py",
        "identity.py",
        "portfolio.py",
        "reason_codes.py",
        "rrg.py",
        "scan_quality_report.py",
        "scanner.py",
        "sector_rotation.py",
        "settings.py",
        "sync_sectors.py",
        "telegram_sender.py",
        "validation.py",
        "visuals.py",
    ]

    def test_all_modules_present(self):
        core_dir = PROJECT_ROOT / "core"
        for mod in self.EXPECTED_MODULES:
            self.assertTrue(
                (core_dir / mod).is_file(),
                f"Missing core module: {mod}"
            )

    def test_module_count(self):
        core_dir = PROJECT_ROOT / "core"
        py_files = list(core_dir.glob("*.py"))
        self.assertEqual(len(py_files), len(self.EXPECTED_MODULES),
                         f"Expected {len(self.EXPECTED_MODULES)} modules, found {len(py_files)}")


class TestProvenanceManifest(unittest.TestCase):
    """Verify the provenance manifest exists and contains valid hashes."""

    def test_manifest_exists(self):
        manifest_path = PROJECT_ROOT / "certificates" / "PROVENANCE_MANIFEST.json"
        self.assertTrue(manifest_path.is_file(),
                        "PROVENANCE_MANIFEST.json not found")

    def test_manifest_valid_json(self):
        import json
        manifest_path = PROJECT_ROOT / "certificates" / "PROVENANCE_MANIFEST.json"
        if not manifest_path.exists():
            self.skipTest("Manifest not yet created")
        data = json.loads(manifest_path.read_text())
        self.assertIn("modules", data)

    def test_manifest_hashes_match_files(self):
        """Verify each hash in the manifest matches the actual file."""
        import json
        manifest_path = PROJECT_ROOT / "certificates" / "PROVENANCE_MANIFEST.json"
        if not manifest_path.exists():
            self.skipTest("Manifest not yet created")
        data = json.loads(manifest_path.read_text())
        for entry in data.get("modules", []):
            filename = entry.get("filename")
            expected_hash = entry.get("sha256_migrated")
            if filename and expected_hash:
                actual_path = PROJECT_ROOT / "core" / filename
                self.assertTrue(
                    actual_path.exists(),
                    f"Core module {filename} declared in provenance manifest is missing from disk"
                )
                actual_hash = sha256_file(actual_path)
                self.assertEqual(
                    actual_hash, expected_hash,
                    f"Hash mismatch for {filename}: "
                    f"manifest={expected_hash[:16]}... actual={actual_hash[:16]}..."
                )


class TestNoForbiddenArtifacts(unittest.TestCase):
    """Ensure research/paper-trading/campaign artifacts are excluded."""

    def test_no_research_dir(self):
        self.assertFalse((PROJECT_ROOT / "research").exists())

    def test_no_paper_trading_dir(self):
        self.assertFalse((PROJECT_ROOT / "paper_trading").exists())

    def test_no_npz_files(self):
        npz_files = list(PROJECT_ROOT.rglob("*.npz"))
        self.assertEqual(len(npz_files), 0,
                         f"Found NPZ files: {npz_files}")

    def test_no_env_file(self):
        """Real .env should not be committed."""
        env = PROJECT_ROOT / ".env"
        if env.exists():
            # Verify it's gitignored
            gitignore = (PROJECT_ROOT / ".gitignore").read_text()
            self.assertIn(".env", gitignore)

    def test_no_universe_db_in_repo(self):
        """universe.db should be provisioned separately, not in VCS."""
        gitignore = (PROJECT_ROOT / ".gitignore").read_text()
        self.assertIn("universe.db", gitignore)


if __name__ == "__main__":
    unittest.main(verbosity=2)
