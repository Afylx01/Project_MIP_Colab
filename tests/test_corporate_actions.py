"""
tests/test_corporate_actions.py - Verifies corporate actions tracking and degradation flags.
"""
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.cube_builder import build_tensor_cube


class TestCorporateActions(unittest.TestCase):
    def test_corporate_action_failure_degrades_metric(self):
        """Cube builder must flag when corporate action adjustment fails."""
        with patch("core.analytical_price.AnalyticalPriceEngine", side_effect=Exception("DB connection simulated failure")):
            cube = build_tensor_cube(
                universe_name="NIFTY500",
                start_date="2020-01-01",
                end_date="2020-05-29"
            )
            self.assertTrue(hasattr(cube, "corporate_actions_bypassed"))
            self.assertTrue(cube.corporate_actions_bypassed)

    def test_bridge_sweep_quarantines_degraded_results(self):
        """Simulation runner must tag corporate action failures as DEGRADED_CORPORATE_ACTIONS."""
        from brute_force.bridge import NativeBruteForceEngine
        from brute_force.cube_builder import TensorCubeContainer
        import numpy as np

        engine = NativeBruteForceEngine()
        dates = ["2020-01-01", "2020-01-02", "2020-01-03"]
        px = np.ones((3, 1), dtype=np.float32) * 100.0
        cube = TensorCubeContainer(
            dates=dates,
            symbols=["TEST"],
            corporate_actions_bypassed=True,
            open_px=px,
            close_px=px,
        )
        param = {"param_id": 1, "initial_capital": 100000.0}
        df = engine.run_sweep(cube, [param])
        self.assertTrue(df.iloc[0]["corporate_actions_bypassed"])
        self.assertEqual(df.iloc[0]["status"], "DEGRADED_CORPORATE_ACTIONS")


if __name__ == "__main__":
    unittest.main()
