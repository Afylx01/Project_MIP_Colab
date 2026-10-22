"""
tests/test_cagr_invariant.py - Verifies that CAGR mathematically derives from ending_equity / initial_capital
without arbitrary clamps or distortions.
"""
import unittest
import numpy as np
import math
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.bridge import NativeBruteForceEngine
from brute_force.cube_builder import TensorCubeContainer


class TestCAGRInvariant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = NativeBruteForceEngine()

    def test_cagr_matches_total_return(self):
        """CAGR must mathematically derive from ending_equity / initial_capital without arbitrary clamps."""
        # 99.95% loss scenario: asset drops from 100 to 0.05
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        px[1:, 0] = np.linspace(100.0, 0.05, 29, dtype=np.float32)

        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["TEST_SYM"],
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )

        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 29,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }

        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]

        expected_total_return = ((row["ending_equity"] - 100_000.0) / 100_000.0) * 100.0
        self.assertAlmostEqual(row["total_return"], expected_total_return, places=2)

        years = (29 - 0) / 252.0
        if years < 0.0833:
            years = 0.0833
        ratio = row["ending_equity"] / 100_000.0
        expected_cagr = (pow(ratio, 1.0 / years) - 1.0) * 100.0 if ratio > 0 else -100.0
        self.assertAlmostEqual(row["cagr"], expected_cagr, places=1)

    def test_legitimate_total_loss_not_insufficient(self):
        """Catastrophic 100% loss (ending_equity == 0) is a valid financial outcome, not DATA_INSUFFICIENT."""
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        px[29, 0] = 0.0
        mask = np.ones((num_dates, 1), dtype=np.uint8)
        mask[29, 0] = 0  # Delisted on final session

        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["TEST_SYM"],
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )

        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 29,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }

        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["ending_equity"], 0.0)
        self.assertEqual(row["cagr"], -100.0)
        self.assertFalse(row["data_insufficient"])
        self.assertEqual(row["status"], "VALID")


if __name__ == "__main__":
    unittest.main()
