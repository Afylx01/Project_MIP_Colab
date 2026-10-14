"""
tests/test_universe_point_in_time.py
Point-in-Time Correctness, Survivorship Bias, and Look-Ahead Prevention Suite
Critical Tier Audit per AGENTS.md §1
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import (
    get_connection,
    get_db_path,
    load_authoritative_trading_calendar,
    get_base_dir,
)
from core.analytical_price import AnalyticalPriceEngine, ActionNature


class TestSurvivorshipCorrectness(unittest.TestCase):
    """Verifies delisted and merged securities are preserved point-in-time without retroactive loss."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = get_db_path()
        if not cls.db_path.exists():
            raise unittest.SkipTest(f"Database not found at {cls.db_path}")
        cls.conn = sqlite3.connect(f"file:{cls.db_path}?mode=ro", uri=True)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_known_delisted_tickers_present(self):
        """Delisted tickers (DHFL, ABAN, CORPBANK) must exist in prices."""
        cursor = self.conn.cursor()
        targets = ["DHFL", "ABAN", "CORPBANK"]
        placeholders = ",".join("?" for _ in targets)
        cursor.execute(f"SELECT DISTINCT symbol FROM prices WHERE symbol IN ({placeholders});", targets)
        found = {r[0] for r in cursor.fetchall()}
        for sym in targets:
            self.assertIn(sym, found, f"Delisted symbol {sym} missing from universe.db (survivorship bias violation)")

    def test_historical_bars_exist_for_delisted_tickers_during_active_years(self):
        """DHFL, ABAN, CORPBANK must retain all historical trading bars during active years."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prices WHERE symbol='DHFL' AND date BETWEEN '2018-01-01' AND '2018-12-31';")
        cnt_2018 = cursor.fetchone()[0]
        self.assertGreater(cnt_2018, 200, "DHFL historical bars missing for active calendar year 2018")

        cursor.execute("SELECT COUNT(*) FROM prices WHERE symbol='ABAN' AND date BETWEEN '2017-01-01' AND '2017-12-31';")
        cnt_aban = cursor.fetchone()[0]
        self.assertGreater(cnt_aban, 200, "ABAN historical bars missing for active calendar year 2017")


class TestLookAheadAndCorporateActionSequencing(unittest.TestCase):
    """Verifies corporate actions are strictly effective-dated on or before ex-date."""

    def setUp(self):
        self.engine = AnalyticalPriceEngine()

    def test_vedl_demerger_active_on_ex_date(self):
        """VEDL demerger must be active and partitioned on ex-date 2026-04-30."""
        actions = self.engine.get_active_actions("VEDL", as_of_date="2026-04-30")
        self.assertTrue(len(actions) > 0, "VEDL demerger action not active on its ex-date 2026-04-30")
        altering = [a for a in actions if a.action_nature == ActionNature.ENTERPRISE_ALTERING]
        self.assertEqual(len(altering), 1, "VEDL enterprise-altering action missing on ex-date")

    def test_future_corporate_actions_strictly_invisible(self):
        """Corporate action must be invisible when as_of_date is strictly before ex_date."""
        actions_pre = self.engine.get_active_actions("PGIL", as_of_date="2026-09-10")
        self.assertEqual(len(actions_pre), 0, "Future corporate action visible before ex-date")
        actions_post = self.engine.get_active_actions("PGIL", as_of_date="2026-09-11")
        self.assertEqual(len(actions_post), 1, "Corporate action not active on ex-date")


class TestUniverseReconstructionIntegrity(unittest.TestCase):
    """Verifies index membership historical reproducibility and clean snapshot storage."""

    def test_no_mock_test_fixtures_in_production_snapshots(self):
        """constituent_snapshots.json must contain 0 synthetic/mock tickers under LIVE-VERIFIED."""
        snap_path = get_base_dir() / "data" / "constituent_snapshots.json"
        if not snap_path.exists():
            return
        with open(snap_path, "r", encoding="utf-8") as f:
            history = json.load(f)
        
        for universe, records in history.items():
            for rec in records:
                source_url = str(rec.get("source_url", ""))
                status = str(rec.get("status", ""))
                symbols = rec.get("symbols", [])
                if "mock" in source_url or any(s.startswith("TICKER") for s in symbols):
                    self.assertNotEqual(
                        status, "LIVE-VERIFIED",
                        f"Pollution violation in {universe}: mock fixture marked as LIVE-VERIFIED from {source_url}"
                    )

    def test_authoritative_calendar_cryptographic_parity(self):
        """load_authoritative_trading_calendar() must load cleanly without hash mismatch."""
        try:
            dates = load_authoritative_trading_calendar()
        except Exception as e:
            self.fail(f"load_authoritative_trading_calendar failed cryptographic verification: {e}")
        self.assertGreater(len(dates), 4800, "Trading calendar has insufficient session count")


if __name__ == "__main__":
    unittest.main()
