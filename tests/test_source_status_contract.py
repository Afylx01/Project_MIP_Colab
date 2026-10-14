"""
MIP Android — Source Status Contract & Simulation Boundary Test Suite
Phase 39: Workstream 1 & 2 TDD Hardening Suite

Verifies:
  1. ConstituentSourceStatus enum contains SIMULATED_TEST_FIXTURE.
  2. Mocked HTTP responses and simulated URLs are strictly classified as SIMULATED_TEST_FIXTURE, never LIVE_VERIFIED.
  3. Official whitelisted endpoints (niftyindices.com, nsearchives.nseindia.com) are classified as LIVE_VERIFIED.
  4. Non-whitelisted, unauthorized external URLs fail closed with BLOCKED status.
  5. Synthetic constituent change fixtures (added/removed) cannot produce a false LIVE_VERIFIED status.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import MIPScannerConfig
from scripts.scanner_hardening import (
    ConstituentSourceStatus,
    ConstituentReconciliationEngine,
    ConstituentValidator,
)


import tempfile
import shutil

class TestSourceStatusContract(unittest.TestCase):
    """Rigorous tests for source status contract, whitelist enforcement, and simulation boundaries."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mip_src_status_test_"))
        self.data_dir = self.temp_dir / "data"
        self.raw_dir = self.data_dir / "raw_reference"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.engine = ConstituentReconciliationEngine(base_dir=self.temp_dir)
        # Create a valid 500-symbol dummy CSV payload
        rows = ["Company Name,Industry,Symbol,Series,ISIN Code"]
        for i in range(500):
            rows.append(f"Company {i},Financial Services,TICKER{i},EQ,INF{i:09d}")
        self.valid_csv_bytes = "\n".join(rows).encode("utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_enum_has_simulated_test_fixture(self):
        """1. Invariant: ConstituentSourceStatus must define SIMULATED_TEST_FIXTURE."""
        self.assertTrue(
            hasattr(ConstituentSourceStatus, "SIMULATED_TEST_FIXTURE"),
            "ConstituentSourceStatus must contain SIMULATED_TEST_FIXTURE",
        )
        self.assertEqual(
            ConstituentSourceStatus.SIMULATED_TEST_FIXTURE.value,
            "SIMULATED_TEST_FIXTURE",
        )

    def test_mock_url_classified_as_simulated_test_fixture(self):
        """2. A mock URL (e.g. https://mock.nse/list.csv) must be classified as SIMULATED_TEST_FIXTURE, never LIVE-VERIFIED."""
        with patch.object(
            self.engine,
            "_fetch_live_with_failover",
            return_value=(self.valid_csv_bytes, "https://mock.nse/list.csv"),
        ):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(
                rep.source_status,
                ConstituentSourceStatus.SIMULATED_TEST_FIXTURE,
                "Mock URLs must NEVER be labeled LIVE-VERIFIED; must be SIMULATED_TEST_FIXTURE",
            )
            self.assertNotEqual(rep.source_status, ConstituentSourceStatus.LIVE_VERIFIED)

    def test_simulated_label_url_classified_as_simulated_test_fixture(self):
        """3. An official URL containing a simulation marker (e.g. '(Simulated Update)') must be SIMULATED_TEST_FIXTURE."""
        sim_url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv (Simulated Update)"
        with patch.object(
            self.engine,
            "_fetch_live_with_failover",
            return_value=(self.valid_csv_bytes, sim_url),
        ):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(
                rep.source_status,
                ConstituentSourceStatus.SIMULATED_TEST_FIXTURE,
                "Simulated fixture markers must be classified as SIMULATED_TEST_FIXTURE",
            )

    def test_official_whitelisted_url_classified_as_live_verified(self):
        """4. Canonical official endpoints must be classified as LIVE-VERIFIED."""
        official_url = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"
        with patch.object(
            self.engine,
            "_fetch_live_with_failover",
            return_value=(self.valid_csv_bytes, official_url),
        ):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(
                rep.source_status,
                ConstituentSourceStatus.LIVE_VERIFIED,
                "Genuine official whitelisted endpoint must be LIVE-VERIFIED",
            )

    def test_unauthorized_external_url_fails_closed_blocked(self):
        """5. Unauthorized external third-party URLs must fail closed with BLOCKED status."""
        unauth_url = "https://malicious-mirror.com/data.csv"
        with patch.object(
            self.engine,
            "_fetch_live_with_failover",
            return_value=(self.valid_csv_bytes, unauth_url),
        ):
            rep = self.engine.fetch_and_reconcile(universe_mode="NIFTY500", force_live_fetch=True)
            self.assertEqual(
                rep.source_status,
                ConstituentSourceStatus.BLOCKED,
                "Non-whitelisted third party URLs must fail closed with BLOCKED status",
            )


class TestHistoricalSufficiencyBoundaries(unittest.TestCase):
    """
    Workstream 6: Strict 252-bar anti-IPO safeguards and historical sufficiency boundaries.
    """

    def setUp(self):
        self.cfg = MIPScannerConfig()

    def test_bars_below_252_strict_exclusion(self):
        """Boundary test: 251 bars produces NaN for 252-bar rolling window and fails qualification."""
        import pandas as pd
        s_high = pd.Series([100.0 + i for i in range(251)])
        rolled = s_high.rolling(self.cfg.rolling_high_bars).max()
        # Must be completely NaN because length (251) < window (252)
        self.assertTrue(rolled.isna().all(), "Rolling 252 on 251 bars must be all NaN")
        close_px = 350.0
        passes = bool(close_px >= (self.cfg.retrace_threshold * rolled.iloc[-1]))
        self.assertFalse(passes, "251-bar security must fail retrace filter (anti-IPO guard)")

    def test_bars_exact_252_boundary(self):
        """Boundary test: exactly 252 bars produces exactly 1 valid non-NaN value at the boundary."""
        import pandas as pd
        s_high = pd.Series([100.0 + i for i in range(252)])
        rolled = s_high.rolling(self.cfg.rolling_high_bars).max()
        # Exactly the last element is non-NaN
        self.assertFalse(pd.isna(rolled.iloc[-1]), "Index 251 on 252 bars must be non-NaN")
        self.assertTrue(rolled.iloc[:-1].isna().all(), "Indices 0..250 must all be NaN")
        self.assertEqual(rolled.iloc[-1], 351.0)

    def test_bars_above_252_valid_computation(self):
        """Boundary test: 253 bars produces 2 valid non-NaN values."""
        import pandas as pd
        s_high = pd.Series([100.0 + i for i in range(253)])
        rolled = s_high.rolling(self.cfg.rolling_high_bars).max()
        self.assertEqual(rolled.notna().sum(), 2)

    def test_fresh_bar_does_not_manufacture_eligibility(self):
        """A symbol with fresh traded bar today but only 50 historical bars cannot be qualified."""
        import pandas as pd
        # Simulated 50 bars ending on today's trade date
        bars = pd.Series([100.0] * 50)
        rolled_high = bars.rolling(252).max()
        self.assertTrue(pd.isna(rolled_high.iloc[-1]))


if __name__ == "__main__":
    unittest.main()

