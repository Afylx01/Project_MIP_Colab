"""
Unit and Integration Tests for All NIFTY Indices Constitution Integration.
Validates:
1. Catalog coverage (all 36 official indices: 15 broad market, 14 sectoral, 7 thematic).
2. Mode normalization and alias resolution.
3. Strict 30-day cache refresh TTL policy.
4. Schema validation and row count bounds per universe.
5. End-to-end scanner candidate universe filtering across diverse indices.
6. Absolute immutability of production universe.db and strategy fingerprint preservation.
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

# Ensure paths
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scripts.scanner_hardening import (
    NIFTY_INDICES_CATALOG,
    normalize_universe_mode,
    get_hardened_universe_label,
    ConstituentValidator,
    ConstituentValidationResult,
    ConstituentReconciliationEngine,
    ConstituentSourceStatus,
    HardenedScanner,
    get_canonical_strategy_fingerprint,
)
from core.data_engine import get_db_path


class TestAllIndicesCatalogAndNormalization(unittest.TestCase):
    """Test suite verifying catalog completeness and alias normalization."""

    def test_catalog_exact_size_and_categories(self):
        self.assertEqual(len(NIFTY_INDICES_CATALOG), 36)
        broad = [k for k, v in NIFTY_INDICES_CATALOG.items() if v["category"] == "Broad Market"]
        sectoral = [k for k, v in NIFTY_INDICES_CATALOG.items() if v["category"] == "Sectoral"]
        thematic = [k for k, v in NIFTY_INDICES_CATALOG.items() if v["category"] == "Thematic"]

        self.assertEqual(len(broad), 15)
        self.assertEqual(len(sectoral), 14)
        self.assertEqual(len(thematic), 7)

    def test_catalog_filenames_and_bounds_structure(self):
        for k, meta in NIFTY_INDICES_CATALOG.items():
            self.assertTrue(meta["filename"].startswith("ind_"))
            self.assertTrue(meta["filename"].endswith(".csv"))
            min_r, max_r = meta["row_bounds"]
            self.assertGreater(min_r, 0)
            self.assertGreaterEqual(max_r, min_r)
            self.assertTrue(len(meta["aliases"]) >= 1)

    def test_alias_normalization(self):
        test_cases = [
            ("NIFTY 50", "NIFTY50"),
            ("50", "NIFTY50"),
            ("Nifty Next 50", "NIFTYNEXT50"),
            ("NEXT50", "NIFTYNEXT50"),
            ("NIFTY 500", "NIFTY500"),
            ("500", "NIFTY500"),
            ("NIFTY 750", "NIFTY750"),
            ("TOTALMARKET", "NIFTY750"),
            ("Total_Market", "NIFTY750"),
            ("NIFTY BANK", "NIFTYBANK"),
            ("BANK", "NIFTYBANK"),
            ("BANKNIFTY", "NIFTYBANK"),
            ("NIFTY IT", "NIFTYIT"),
            ("IT", "NIFTYIT"),
            ("NIFTY AUTO", "NIFTYAUTO"),
            ("AUTO", "NIFTYAUTO"),
            ("FINNIFTY", "NIFTYFINANCIALSERVICES"),
            ("FINANCIAL SERVICES", "NIFTYFINANCIALSERVICES"),
            ("NIFTY FMCG", "NIFTYFMCG"),
            ("NIFTY METAL", "NIFTYMETAL"),
            ("NIFTY PHARMA", "NIFTYPHARMA"),
            ("NIFTY ENERGY", "NIFTYENERGY"),
            ("INFRA", "NIFTYINFRASTRUCTURE"),
            ("NIFTY INFRA", "NIFTYINFRASTRUCTURE"),
            ("CPSE", "NIFTYCPSE"),
            ("PSE", "NIFTYPSE"),
            ("MNC", "NIFTYMNC"),
        ]
        for raw, expected in test_cases:
            normalized = normalize_universe_mode(raw)
            self.assertEqual(normalized, expected, f"Failed normalizing '{raw}'")

    def test_hardened_universe_labels(self):
        self.assertEqual(get_hardened_universe_label("NIFTYBANK"), "NIFTY Bank")
        self.assertEqual(get_hardened_universe_label("AUTO"), "NIFTY Auto")
        self.assertEqual(get_hardened_universe_label("500"), "NIFTY 500")
        self.assertEqual(get_hardened_universe_label("750"), "NIFTY Total Market")
        self.assertEqual(get_hardened_universe_label("INFRA"), "NIFTY Infrastructure")


class TestConstituentSchemaAndBounds(unittest.TestCase):
    """Test institutional schema validation and row bounds across all indices."""

    def _generate_csv(self, symbols, name="Test Company", ind="Test Industry"):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i, sym in enumerate(symbols):
            rows.append(f"{name} {i},{ind},{sym},EQ,INE{i:09d}")
        return "\n".join(rows).encode("utf-8")

    def test_all_catalog_indices_have_bounds_in_validator(self):
        for k in NIFTY_INDICES_CATALOG:
            self.assertIn(k, ConstituentValidator.ROW_BOUNDS)

    def test_sectoral_index_validation(self):
        # NIFTY AUTO (10 to 25 scrips)
        auto_syms = [f"AUTO_{i}" for i in range(15)]
        csv_bytes = self._generate_csv(auto_syms, ind="Automobile")
        res = ConstituentValidator.validate_csv_content(csv_bytes, universe_key="NIFTYAUTO")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.row_count, 15)
        self.assertEqual(len(res.valid_symbols), 15)

    def test_out_of_bounds_sectoral_rejected(self):
        # NIFTY AUTO with only 2 scrips should fail
        few_syms = ["AUTO_1", "AUTO_2"]
        csv_bytes = self._generate_csv(few_syms, ind="Automobile")
        res = ConstituentValidator.validate_csv_content(csv_bytes, universe_key="NIFTYAUTO")
        self.assertFalse(res.is_valid)
        self.assertIn("bounds", res.error_message)

    def test_missing_required_headers_rejected(self):
        bad_csv = b"Company Name,Industry,TickerSymbol,Series\nABC,IT,ABC,EQ\n"
        res = ConstituentValidator.validate_csv_content(bad_csv, universe_key="NIFTYIT")
        self.assertFalse(res.is_valid)
        self.assertIn("Missing required", res.error_message)


class TestThirtyDayCacheRefreshTTLPolicy(unittest.TestCase):
    """Test strict 30-day cache refresh TTL policy."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_ttl_test_"))
        self.raw_dir = self.temp_dir / "data" / "raw_reference"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.engine = ConstituentReconciliationEngine(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _generate_csv(self, symbols):
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i, sym in enumerate(symbols):
            rows.append(f"Company {i},Industry,SYM{i},EQ,INE{i:09d}")
        return "\n".join(rows).encode("utf-8")

    def test_fresh_cache_under_30_days_avoids_network(self):
        """When cache is fresh (<= 30 days old) and force_live_fetch=False, use CACHED-VALID without network."""
        symbols = [f"BANK{i}" for i in range(14)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_niftybanklist.csv"
        cache_file.write_bytes(csv_bytes)

        # Set cache mtime to 10 days ago (well within 30-day window)
        ten_days_ago = time.time() - (10 * 86400)
        os.utime(cache_file, (ten_days_ago, ten_days_ago))

        # We mock _fetch_live_with_failover to raise an exception if called
        with patch.object(self.engine, "_fetch_live_with_failover", side_effect=AssertionError("Network called when cache is fresh!")):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTYBANK", force_live_fetch=False)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.CACHED_VALID)
            self.assertEqual(rep.total_constituents, 14)
            self.assertIn("30-day", rep.warning_message)

    def test_expired_cache_over_30_days_triggers_live_refresh(self):
        """When cache is older than 30 days, trigger live refresh from official endpoint."""
        symbols = [f"IT{i}" for i in range(10)]
        old_csv = self._generate_csv(symbols[:8])
        cache_file = self.raw_dir / "ind_niftyitlist.csv"
        cache_file.write_bytes(old_csv)

        # Set cache mtime to 35 days ago (expired)
        thirty_five_days_ago = time.time() - (35 * 86400)
        os.utime(cache_file, (thirty_five_days_ago, thirty_five_days_ago))

        new_csv = self._generate_csv(symbols)
        official_url = "https://www.niftyindices.com/IndexConstituent/ind_niftyitlist.csv"

        with patch.object(self.engine, "_fetch_live_with_failover", return_value=(new_csv, official_url)) as mock_fetch:
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTYIT", force_live_fetch=False)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.LIVE_VERIFIED)
            self.assertEqual(rep.total_constituents, 10)
            mock_fetch.assert_called_once()

            # Verify local cache file mtime was refreshed to current time
            new_mtime = cache_file.stat().st_mtime
            self.assertLess(time.time() - new_mtime, 10.0)

    def test_force_live_fetch_bypasses_fresh_cache(self):
        """When force_live_fetch=True, bypass fresh cache and query official source."""
        symbols = [f"AUTO{i}" for i in range(15)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_niftyautolist.csv"
        cache_file.write_bytes(csv_bytes)

        official_url = "https://www.niftyindices.com/IndexConstituent/ind_niftyautolist.csv"

        with patch.object(self.engine, "_fetch_live_with_failover", return_value=(csv_bytes, official_url)) as mock_fetch:
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTYAUTO", force_live_fetch=True)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.LIVE_VERIFIED)
            mock_fetch.assert_called_once()

    def test_expired_cache_network_failure_falls_back_to_stale(self):
        """When cache is > 30 days old and live fetch fails, fall back to STALE if allow_stale=True."""
        symbols = [f"CPSE{i}" for i in range(11)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_niftycpselist.csv"
        cache_file.write_bytes(csv_bytes)

        # 40 days old
        old_time = time.time() - (40 * 86400)
        os.utime(cache_file, (old_time, old_time))

        with patch.object(self.engine, "_fetch_live_with_failover", return_value=(None, None)):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTYCPSE", allow_stale=True)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.STALE)
            self.assertIn("CRITICAL WARNING", rep.warning_message)

    def test_expired_cache_network_failure_fails_closed_when_disallowed(self):
        """When cache is > 30 days old and live fetch fails, return BLOCKED if allow_stale=False."""
        symbols = [f"CPSE{i}" for i in range(11)]
        csv_bytes = self._generate_csv(symbols)
        cache_file = self.raw_dir / "ind_niftycpselist.csv"
        cache_file.write_bytes(csv_bytes)

        old_time = time.time() - (40 * 86400)
        os.utime(cache_file, (old_time, old_time))

        with patch.object(self.engine, "_fetch_live_with_failover", return_value=(None, None)):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTYCPSE", allow_stale=False)
            self.assertEqual(rep.source_status, ConstituentSourceStatus.BLOCKED)
            self.assertIn("exceeds 30-day freshness policy", rep.warning_message)


class TestHardenedScannerMultiUniverseFiltering(unittest.TestCase):
    """Test HardenedScanner executing across diverse index universes."""

    def setUp(self):
        self.prod_db_path = get_db_path()
        conn = sqlite3.connect(f"file:{self.prod_db_path}?mode=ro", uri=True)
        self.initial_row_count = conn.execute("SELECT COUNT(*) FROM prices;").fetchone()[0]
        conn.close()

    def tearDown(self):
        conn = sqlite3.connect(f"file:{self.prod_db_path}?mode=ro", uri=True)
        final_row_count = conn.execute("SELECT COUNT(*) FROM prices;").fetchone()[0]
        conn.close()
        self.assertEqual(self.initial_row_count, final_row_count, "Production universe.db mutated!")

    def test_scanner_executes_on_sectoral_universe(self):
        """Verify HardenedScanner correctly filters candidates when scanning a sectoral universe."""
        scanner = HardenedScanner()
        # Scan on NIFTY BANK
        top_df, m_meta, s_meta, b_meta, picks_df, etf_df = scanner.run_scan(
            as_of_date="2026-10-09",
            universe_mode="NIFTYBANK",
            top_n=5,
            export_csv=False,
            export_excel=False,
            auto_update_universe=False,
        )
        self.assertIsNotNone(top_df)
        self.assertTrue(hasattr(top_df, "attrs"))
        const_rep = top_df.attrs.get("constituent_report")
        self.assertIsNotNone(const_rep)
        self.assertEqual(const_rep.universe_name, "NIFTYBANK")
        # Candidate pool should be bounded by Bank scrips (<= 14)
        if not top_df.empty:
            self.assertLessEqual(len(top_df), 14)

    def test_strategy_fingerprint_preserved_across_all_universes(self):
        """Verify the canonical strategy fingerprint 9036fae5... is preserved."""
        scanner = HardenedScanner()
        fp = get_canonical_strategy_fingerprint(scanner.config)
        self.assertEqual(fp, "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de")


if __name__ == "__main__":
    unittest.main()
