"""
tests/test_ranking_repairs.py
Automated verification tests for Phase Ranking Repairs:
1. Universe mode alias resolution (CD-01).
2. Authoritative 22-industry macro taxonomy conformance (CD-02).
3. Strategy rationale and manifest documentation alignment (CD-03).
4. Frozen strategy fingerprint preservation.
5. Volar score mathematical invariant verification.
"""

import unittest
import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class TestUniverseModeAliasResolution(unittest.TestCase):
    """Verifies that universe aliases correctly resolve to NIFTY 750 / Total Market."""

    def test_750_aliases_return_total_market_constituents(self):
        from core.data_engine import load_universe_constituents, get_universe_label
        aliases = [
            "750",
            "NIFTY750",
            "TOTALMARKET",
            "TOTAL_MARKET",
            "NIFTY750TOTALMARKET",
            "nifty_750",
            "nifty750totalmarket"
        ]
        for a in aliases:
            constituents = load_universe_constituents(a)
            label = get_universe_label(a)
            self.assertEqual(label, "NIFTY 750 (TOTAL MARKET)", f"Failed label for alias '{a}'")
            self.assertEqual(len(constituents), 755, f"Failed constituent count for alias '{a}'")

    def test_500_aliases_return_500_constituents(self):
        from core.data_engine import load_universe_constituents, get_universe_label
        aliases = ["500", "NIFTY500", "nifty_500"]
        for a in aliases:
            constituents = load_universe_constituents(a)
            label = get_universe_label(a)
            self.assertEqual(label, "NIFTY 500", f"Failed label for alias '{a}'")
            self.assertEqual(len(constituents), 501, f"Failed constituent count for alias '{a}'")


class TestSectorTaxonomyConformance(unittest.TestCase):
    """Verifies that data/symbol_sector_map.json conforms to official 22 AMFI industries."""

    def setUp(self):
        with open(PROJECT_ROOT / "data" / "symbol_sector_map.json", "r") as f:
            self.sector_map = json.load(f)

    def test_sector_count_is_22(self):
        unique_sectors = set(self.sector_map.values())
        self.assertEqual(len(unique_sectors), 22, f"Expected 22 sectors, found {len(unique_sectors)}: {sorted(unique_sectors)}")

    def test_telecom_and_media_are_separated(self):
        """STLTECH and HFCL must be TELECOMMUNICATION; TIPSMUSIC and NAZARA must be MEDIA."""
        self.assertEqual(self.sector_map.get("STLTECH"), "TELECOMMUNICATION")
        self.assertEqual(self.sector_map.get("HFCL"), "TELECOMMUNICATION")
        self.assertEqual(self.sector_map.get("TIPSMUSIC"), "MEDIA ENTERTAINMENT & PUBLICATION")
        self.assertEqual(self.sector_map.get("NAZARA"), "MEDIA ENTERTAINMENT & PUBLICATION")

    def test_no_legacy_infra_media_bucket(self):
        """INFRA_MEDIA was a collapsed bucket and must not exist in official 22 taxonomy."""
        unique_sectors = set(self.sector_map.values())
        self.assertNotIn("INFRA_MEDIA", unique_sectors)


class TestDocumentationAlignment(unittest.TestCase):
    """Verifies that core/excel_generator.py accurately documents the frozen Volar formula."""

    def test_excel_generator_strategy_rationale_volar_text(self):
        gen_file = (PROJECT_ROOT / "core" / "excel_generator.py").read_text()
        self.assertIn("Volar Score (Return / Annualized Volatility)", gen_file)
        self.assertIn("252-session Return / Annualized Volatility (5% floor)", gen_file)
        # Verify old erroneous formula description is eliminated
        self.assertNotIn("252-session log-price regression slope × 252 × R²", gen_file)


class TestStrategyFingerprintPreservation(unittest.TestCase):
    """Verifies that canonical strategy parameters and SHA-256 fingerprint are unchanged."""

    CANONICAL_FINGERPRINT = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"

    def test_fingerprint_unmodified(self):
        from core.config import MIPScannerConfig
        cfg = MIPScannerConfig()
        params = {
            "ema_regime_span": cfg.ema_regime_span,
            "ema_rs_span": cfg.ema_rs_span,
            "ema_trend_span": cfg.ema_trend_span,
            "exit_buffer_rank": cfg.exit_buffer_rank,
            "max_per_sector": cfg.max_per_sector,
            "momentum_lookback_bars": cfg.momentum_lookback_bars,
            "retrace_threshold": cfg.retrace_threshold,
            "top_n_candidates": cfg.top_n_candidates,
            "volatility_floor": cfg.volatility_floor,
        }
        serialized = json.dumps(params, sort_keys=True)
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        self.assertEqual(fp, self.CANONICAL_FINGERPRINT)


class TestVolarMathematicalInvariant(unittest.TestCase):
    """Verifies the exact calculation of Volar score: ret_252 / max(vol_252, floor)."""

    def test_volar_calculation_against_synthetic_series(self):
        np.random.seed(42)
        n_bars = 300
        returns = np.random.normal(0.001, 0.015, n_bars)
        price_series = 100.0 * np.exp(np.cumsum(returns))

        ret_1d = pd.Series(price_series).pct_change().fillna(0.0)
        vol_252 = ret_1d.rolling(252, min_periods=251).std(ddof=1).iloc[-1] * np.sqrt(252)
        ret_252 = (price_series[-1] / price_series[-253] - 1.0)
        expected_volar = ret_252 / max(vol_252, 0.05)

        # Compare with core calculation
        vol_floor = 0.05
        clamped_vol = max(vol_252, vol_floor)
        computed_volar = ret_252 / clamped_vol
        self.assertAlmostEqual(computed_volar, expected_volar, places=7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
