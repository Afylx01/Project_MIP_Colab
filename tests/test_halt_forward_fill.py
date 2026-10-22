"""
tests/test_halt_forward_fill.py - Verifies trading halt price forward-fill and valid_price_mask integrity.
Guards against look-ahead execution bias on halt days per Pillar 1 (Data Integrity) and Pillar 2 (Timing Realism).
"""

import unittest
import sys
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.cube_builder import build_tensor_cube, TensorCubeContainer
from brute_force.bridge import NativeBruteForceEngine


class TestHaltForwardFill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = NativeBruteForceEngine()

    def test_halt_days_forward_fill_prices_while_mask_remains_false(self):
        """
        Verify that internal missing bars (trading halts) forward-fill prices for indicator continuity
        (e.g., ATR-14, EMA), but valid_price_mask STRICTLY remains False so that the simulation
        kernel does not execute trades on halted days.
        """
        # Create synthetic raw_bars for 2 symbols across 5 dates:
        # SYM0 has all 5 dates: d0, d1, d2, d3, d4
        # SYM1 has d0, d1, d3, d4 (d2 is a trading halt / missing bar)
        dates = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
        
        records = []
        for d in dates:
            records.append({
                "date": d,
                "symbol": "SYM0",
                "open": 100.0,
                "high": 105.0,
                "low": 95.0,
                "close": 100.0,
                "volume": 10000.0,
            })
            if d != "2024-01-03":  # SYM1 halted on 2024-01-03 (d2)
                records.append({
                    "date": d,
                    "symbol": "SYM1",
                    "open": 200.0,
                    "high": 210.0,
                    "low": 190.0,
                    "close": 200.0,
                    "volume": 5000.0,
                })

        mock_bars_df = pd.DataFrame(records)

        with patch("pandas.read_sql_query", return_value=mock_bars_df), \
             patch("brute_force.cube_builder.load_symbol_sector_map", return_value={"SYM0": "IT", "SYM1": "FINANCE"}), \
             patch("core.benchmark_validator.resolve_benchmark_dataframe") as mock_bench:
            
            # Mock benchmark dataframe
            mock_bench.return_value = pd.DataFrame({
                "date": dates,
                "close": [1000.0, 1010.0, 1020.0, 1030.0, 1040.0],
                "ema_20": [990.0, 990.0, 990.0, 990.0, 990.0]
            })

            cube = build_tensor_cube(
                start_date="2024-01-01",
                end_date="2024-01-05",
                symbols=["SYM0", "SYM1"],
                benchmark_name="NIFTY500",
            )

            sym1_idx = cube.symbols.index("SYM1")
            d2_idx = cube.dates.index("2024-01-03")

            # 1. Close and Open price must be forward-filled from d1 ("2024-01-02")
            self.assertEqual(cube.close_px[d2_idx, sym1_idx], 200.0, "Close price must be forward-filled on halt day")
            self.assertEqual(cube.open_px[d2_idx, sym1_idx], 200.0, "Open price must be forward-filled on halt day")

            # 2. valid_price_mask on d2 for SYM1 MUST BE FALSE (cannot trade on halt day!)
            self.assertFalse(
                bool(cube.valid_price_mask[d2_idx, sym1_idx]),
                "valid_price_mask must remain False on halt days to prevent execution look-ahead bias!"
            )

            # 3. Non-halt days must be True
            d1_idx = cube.dates.index("2024-01-02")
            d3_idx = cube.dates.index("2024-01-04")
            self.assertTrue(bool(cube.valid_price_mask[d1_idx, sym1_idx]), "Active trading day d1 must be True")
            self.assertTrue(bool(cube.valid_price_mask[d3_idx, sym1_idx]), "Active trading day d3 must be True")

    def test_halt_days_not_tradeable_in_native_engine(self):
        """
        Verify that a stock halted on a rebalance date is strictly excluded from candidate entry
        by the native simulation kernel when valid_price_mask is False.
        """
        num_dates = 10
        dates = [f"2024-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["SYM0", "SYM1"]

        px = np.ones((num_dates, 2), dtype=np.float32) * 100.0
        valid_mask = np.ones((num_dates, 2), dtype=np.uint8)

        # Halt SYM1 at signal date 0
        valid_mask[0, 1] = 0

        # High score for SYM1, lower for SYM0
        volar = np.zeros((4, num_dates, 2), dtype=np.float32)
        volar[0, 0, 0] = 50.0   # SYM0
        volar[0, 0, 1] = 100.0  # SYM1 (halted / masked)

        reb = np.array([0, 9], dtype=np.int32)
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
            "end_date_idx": 9,
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

        # SYM1 was halted/masked, so SYM0 was selected
        self.assertEqual(row["status"], "VALID")
        self.assertEqual(row["ending_equity"], 100_000.0)
        self.assertFalse(row["data_insufficient"])


if __name__ == "__main__":
    unittest.main()
