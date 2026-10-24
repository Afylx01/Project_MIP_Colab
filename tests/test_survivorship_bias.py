"""
tests/test_survivorship_bias.py - Survivorship Bias and Point-in-Time Universe Audit Suite
Verifies that index constituent universe construction adheres strictly to point-in-time
snapshots without look-ahead additions or silent omission of delisted symbols per Pillar 1.
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_base_dir, get_db_path
from brute_force.cube_builder import build_tensor_cube, load_point_in_time_constituents


class TestSurvivorshipBias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_dir = get_base_dir()
        cls.db_path = get_db_path()
        cls.snap_path = cls.base_dir / "data" / "constituent_snapshots.json"

    def test_point_in_time_universe_matches_snapshots(self):
        """
        Point-in-Time Universe Construction:
        Universe constituents built for a target date must match the historical snapshot,
        preventing look-ahead additions and survivorship bias.
        """
        self.assertTrue(self.snap_path.exists(), f"Missing snapshots file: {self.snap_path}")
        with open(self.snap_path, "r", encoding="utf-8") as f:
            snapshots = json.load(f)

        self.assertIn("NIFTY500", snapshots, "NIFTY500 snapshots missing from repository")
        nifty500_snaps = snapshots["NIFTY500"]
        self.assertGreater(len(nifty500_snaps), 0, "No NIFTY500 snapshots recorded")

        # Select earliest recorded snapshot
        first_snap = nifty500_snaps[0]
        snap_date = first_snap.get("snapshot_date") or first_snap.get("date")
        pit_symbols = set(first_snap.get("symbols") or first_snap.get("constituents") or [])
        self.assertGreater(len(pit_symbols), 0, "Snapshot symbols set is empty")

        # Interrogate loader directly
        loaded_pit = load_point_in_time_constituents("NIFTY500", as_of_date=snap_date, base_dir=self.base_dir)
        self.assertIsNotNone(loaded_pit)
        self.assertEqual(loaded_pit, pit_symbols)

        # Mock snapshot test to verify strict subset & no look-ahead additions
        mock_snapshot_db = {
            "NIFTY500": [
                {
                    "snapshot_date": "2010-01-01",
                    "symbols": ["INFY", "TCS", "DHFL", "ABAN"],
                    "sha256": "mock_sha_2010"
                }
            ]
        }
        with patch("builtins.open", unittest.mock.mock_open(read_data=json.dumps(mock_snapshot_db))):
            resolved = load_point_in_time_constituents("NIFTY500", as_of_date="2010-01-01", base_dir=self.base_dir)
            self.assertEqual(resolved, {"INFY", "TCS", "DHFL", "ABAN"})

            # Verify future additions are excluded
            future_resolved = load_point_in_time_constituents("NIFTY500", as_of_date="2009-12-31", base_dir=self.base_dir)
            self.assertIsNone(future_resolved, "Must not load future snapshots when query date is prior to earliest snapshot")

    def test_delisted_tickers_present_in_historical_database(self):
        """
        Pillar 1 Invariant:
        Delisted tickers (e.g. DHFL, ABAN, CORPBANK) must exist in prices database
        so they can be backtested without survivorship bias.
        """
        if not self.db_path.exists():
            raise unittest.SkipTest(f"Database not found at {self.db_path}")

        conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        targets = ["DHFL", "ABAN", "CORPBANK"]
        placeholders = ",".join("?" for _ in targets)
        cursor.execute(f"SELECT DISTINCT symbol FROM prices WHERE symbol IN ({placeholders});", targets)
        found = {r[0] for r in cursor.fetchall()}
        conn.close()

        for sym in targets:
            self.assertIn(sym, found, f"Delisted symbol {sym} missing from universe.db (survivorship bias violation)")

    def test_point_in_time_fallback_requires_explicit_opt_in(self):
        """A window before the PIT table starts must be refused, never silently current-listed."""
        with patch("brute_force.cube_builder.load_point_in_time_constituents", return_value=None):
            with self.assertRaises(ValueError) as cm:
                build_tensor_cube(
                    universe_name="NIFTY500",
                    start_date="2010-01-01",
                    end_date="2013-12-31",
                    point_in_time=True,
                )
            self.assertIn("point-in-time", str(cm.exception).lower())


if __name__ == "__main__":
    unittest.main()
