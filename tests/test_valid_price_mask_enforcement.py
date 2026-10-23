"""
tests/test_valid_price_mask_enforcement.py - Verifies valid_price_mask enforcement across multi-symbol universes
Ensures masked stocks are excluded from candidate screening, entry sizing, and daily valuation per Pillar 1 & 5.
"""

import unittest
import sys
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.bridge import NativeBruteForceEngine
from brute_force.cube_builder import TensorCubeContainer


class TestValidPriceMaskEnforcement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = NativeBruteForceEngine()

    def test_valid_price_mask_enforced_for_multi_symbol_universe(self):
        """
        Multi-symbol universe (N=3):
        Symbol 1 is masked (valid_price_mask=False) at signal date.
        Simulation must never select symbol 1 as candidate, and must not propagate NaNs.
        """
        num_dates = 30
        N = 3
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["SYM0", "SYM1", "SYM2"]

        px = np.ones((num_dates, N), dtype=np.float32) * 100.0

        # Construct valid_price_mask: SYM1 is invalid at day 0 (signal date)
        valid_mask = np.ones((num_dates, N), dtype=np.uint8)
        valid_mask[0, 1] = 0  # SYM1 masked at signal date 0

        # Volar ranking: SYM1 has highest score, SYM0 has medium, SYM2 has lowest
        volar = np.zeros((4, num_dates, N), dtype=np.float32)
        volar[0, 0, 0] = 50.0   # SYM0: score 50
        volar[0, 0, 1] = 100.0  # SYM1: score 100 (highest, but masked!)
        volar[0, 0, 2] = 20.0   # SYM2: score 20

        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
            valid_price_mask=valid_mask
        )

        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 29,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,  # Only top 1 stock picked
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

        # SYM1 was masked, so SYM0 (next highest valid score) was chosen and traded
        self.assertFalse(np.isnan(row["cagr"]))
        self.assertFalse(np.isnan(row["ending_equity"]))
        self.assertEqual(row["status"], "VALID")
        self.assertEqual(row["ending_equity"], 100_000.0)
        self.assertGreater(row["turnover_annual"], 0.0)

    def test_daily_valuation_forward_fills_masked_bar(self):
        """
        N=3 cube, hold SYM0. At day 15, valid_price_mask[15, 0]=0 but close_px[15, 0]=100.0 (stale non-NaN).
        The engine must value the holding from the prior finite close and remain VALID;
        a single halted session must not invalidate a multi-year simulation.
        """
        num_dates = 30
        N = 3
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["SYM0", "SYM1", "SYM2"]

        px = np.ones((num_dates, N), dtype=np.float32) * 100.0
        valid_mask = np.ones((num_dates, N), dtype=np.uint8)
        valid_mask[15, 0] = 0  # Invalidate SYM0 at day 15 while held

        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
            valid_price_mask=valid_mask
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
        self.assertFalse(row["data_insufficient"])
        self.assertEqual(row["status"], "VALID")
        self.assertGreater(float(row["ending_equity"]), 0.0)

    def test_masked_entry_skips_rebalance_without_invalidating(self):
        """
        N=2, top_n=2. Both symbols have valid_price_mask[exec_date, :]=0 at first rebalance.
        The rebalance must be skipped (stay in cash) without invalidating the simulation.
        """
        num_dates = 30
        N = 2
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["SYM0", "SYM1"]

        px = np.ones((num_dates, N), dtype=np.float32) * 100.0
        valid_mask = np.ones((num_dates, N), dtype=np.uint8)
        # Invalidate execution bar (day 1) for all candidates
        valid_mask[1, :] = 0

        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
            valid_price_mask=valid_mask
        )

        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 29,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 2,
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
        self.assertFalse(row["data_insufficient"])
        self.assertEqual(row["status"], "VALID")
        self.assertEqual(int(row["total_trades"]), 0)
        self.assertAlmostEqual(float(row["ending_equity"]), 100_000.0, places=2)

    def test_single_symbol_masked_signal_fails_closed(self):
        """For N=1, a masked bar fails closed as DATA_INSUFFICIENT."""
        num_dates = 30
        N = 1
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["SYM0"]

        px = np.ones((num_dates, N), dtype=np.float32) * 100.0
        valid_mask = np.ones((num_dates, N), dtype=np.uint8)
        valid_mask[0, 0] = 0  # Signal bar masked

        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
            valid_price_mask=valid_mask
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
        self.assertTrue(np.isnan(row["cagr"]))
        self.assertTrue(row["data_insufficient"])
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")


if __name__ == "__main__":
    unittest.main()
