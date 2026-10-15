"""
test_multi_schedule_brute_force.py - Contract Tests for Multi-Schedule, Multi-Era Native Brute Force Engine
Target Architecture: ARMv8.2-A NEON on Snapdragon 8 Gen 2 / Termux PRoot
"""

import unittest
import numpy as np
import pandas as pd
from pathlib import Path

from brute_force.bridge import (
    NativeBruteForceEngine,
    compile_native_kernel,
    CSimulationSummary,
    CSimParams,
    CTensorCube,
    SCHEDULE_WEEKLY,
    SCHEDULE_MONTHLY,
    SCHEDULE_QUARTERLY,
    SCHEDULE_HALF_YEARLY,
    SCHEDULE_YEARLY,
    FILTER_RETRACE,
    FILTER_TREND,
    FILTER_RS,
    FILTER_REGIME,
    FILTER_SECTOR_CAP,
    CANONICAL_FILTER_FLAGS,
)
from brute_force.cube_builder import build_tensor_cube, TensorCubeContainer
from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (
    get_canonical_baseline_param,
    generate_tier1_baseline_matrix,
    generate_tier2_ablation_grid,
    MACRO_ERAS,
)


class TestMultiScheduleBruteForce(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.so_path = compile_native_kernel(force_recompile=True)
        # Build tensor cube once for testing
        cls.cube = build_tensor_cube(
            start_date="2016-01-01",
            end_date="2026-08-31",
            universe_name="NIFTY500",
        )
        cls.runner = BruteForceCampaignRunner(cube=cls.cube)

    def test_01_struct_sizes_and_alignment(self):
        import ctypes
        self.assertEqual(ctypes.sizeof(CSimulationSummary), 48)
        self.assertEqual(ctypes.sizeof(CSimParams), 64)
        self.assertEqual(ctypes.sizeof(CTensorCube), 192)

    def test_02_cube_schedules_generated(self):
        self.assertEqual(self.cube.num_schedules, 5)
        self.assertGreater(self.cube.schedule_lengths[SCHEDULE_WEEKLY], 400)
        self.assertGreater(self.cube.schedule_lengths[SCHEDULE_MONTHLY], 100)
        self.assertGreater(self.cube.schedule_lengths[SCHEDULE_QUARTERLY], 30)
        self.assertGreater(self.cube.schedule_lengths[SCHEDULE_HALF_YEARLY], 15)
        self.assertGreater(self.cube.schedule_lengths[SCHEDULE_YEARLY], 8)

    def test_03_all_five_schedules_execute_cleanly(self):
        schedules = ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]
        for sched in schedules:
            res = self.runner.run_baseline(
                start_date="2016-01-01",
                end_date="2026-08-31",
                schedule=sched,
            )
            self.assertIn("cagr_pct", res)
            self.assertGreater(res["ending_equity"], 500_000.0)
            self.assertGreater(res["cagr_pct"], 0.0, f"CAGR for {sched} should be positive")
            self.assertGreaterEqual(res["max_drawdown_pct"], 0.0)
            self.assertGreater(res["turnover_annual_pct"], 0.0)
            self.assertGreater(res["total_trades"], 0)

    def test_04_macro_era_window_clipping(self):
        # Test 2020-2021 Covid era
        covid_param = get_canonical_baseline_param()
        start_d, end_d, _ = MACRO_ERAS["2020-2021"]
        covid_param["start_date"] = start_d
        covid_param["end_date"] = end_d
        covid_param["start_date_idx"] = min([self.cube.date_to_idx[d] for d in self.cube.dates if d >= start_d])
        covid_param["end_date_idx"] = max([self.cube.date_to_idx[d] for d in self.cube.dates if d <= end_d])
        covid_param["schedule_idx"] = SCHEDULE_MONTHLY

        df = self.runner.run_sweep([covid_param], num_threads=1)
        self.assertEqual(len(df), 1)
        row = df.iloc[0]
        self.assertGreater(row["ending_equity"], 1_000_000.0)
        self.assertGreater(row["cagr"], 0.0)

    def test_05_filter_ablation_modifies_behavior(self):
        base_param = get_canonical_baseline_param()
        base_param["param_id"] = 0
        base_param["filter_flags"] = CANONICAL_FILTER_FLAGS

        # Retrace OFF
        no_retrace = get_canonical_baseline_param()
        no_retrace["param_id"] = 1
        no_retrace["filter_flags"] = CANONICAL_FILTER_FLAGS & ~FILTER_RETRACE

        # RS OFF
        no_rs = get_canonical_baseline_param()
        no_rs["param_id"] = 2
        no_rs["filter_flags"] = CANONICAL_FILTER_FLAGS & ~FILTER_RS

        df = self.runner.run_sweep([base_param, no_retrace, no_rs], num_threads=1)
        self.assertEqual(len(df), 3)

        # Confirm trade count and results differ between filtered and unfiltered
        trades_base = df.loc[df["param_id"] == 0, "total_trades"].values[0]
        trades_no_retrace = df.loc[df["param_id"] == 1, "total_trades"].values[0]
        trades_no_rs = df.loc[df["param_id"] == 2, "total_trades"].values[0]
        self.assertNotEqual(trades_base, trades_no_retrace)
        self.assertNotEqual(trades_base, trades_no_rs)

    def test_06_equal_weight_vs_atr_risk_parity(self):
        p_atr = get_canonical_baseline_param()
        p_atr["param_id"] = 0
        p_atr["sizing_mode"] = "atr_risk_parity"

        p_ew = get_canonical_baseline_param()
        p_ew["param_id"] = 1
        p_ew["sizing_mode"] = "equal_weight"

        df = self.runner.run_sweep([p_atr, p_ew], num_threads=2)
        self.assertEqual(len(df), 2)
        cagr_atr = df.loc[df["param_id"] == 0, "cagr"].values[0]
        cagr_ew = df.loc[df["param_id"] == 1, "cagr"].values[0]
        self.assertGreater(cagr_atr, 0.0)
        self.assertGreater(cagr_ew, 0.0)


    def test_07_run_custom_backtest_contracts(self):
        res = self.runner.run_custom_backtest(
            start_date="2020-01-01",
            end_date="2024-12-31",
            universe_name="NIFTY500",
            schedule="monthly",
            lookback=252,
            ema_trend=200,
            top_n=20,
        )
        self.assertEqual(res["config_type"], "CUSTOM_BACKTEST")
        self.assertIn("cagr_pct", res)
        self.assertIn("sharpe_ratio", res)
        self.assertIn("sortino_ratio", res)
        self.assertIn("calmar_ratio", res)
        self.assertIn("max_drawdown_pct", res)
        self.assertIn("rebalance_dates", res)
        self.assertIn("equity_curve", res)
        self.assertIn("benchmark_equity", res)
        self.assertIn("drawdown_pct_series", res)
        self.assertEqual(len(res["rebalance_dates"]), len(res["equity_curve"]))
        self.assertEqual(len(res["equity_curve"]), len(res["benchmark_equity"]))
        self.assertEqual(len(res["equity_curve"]), len(res["drawdown_pct_series"]))
        self.assertGreater(res["ending_equity"], 0.0)

    def test_08_run_custom_sweep_contracts(self):
        df = self.runner.run_custom_sweep(
            lookbacks=[189, 252],
            ema_trends=[150, 200],
            top_ns=[20],
            schedules=["monthly"],
            start_date="2020-01-01",
            end_date="2024-12-31",
            universe_name="NIFTY500",
            num_threads=2,
        )
        self.assertEqual(len(df), 4)
        self.assertIn("sharpe", df.columns)
        self.assertIn("cagr", df.columns)
        self.assertIn("max_drawdown", df.columns)
        self.assertTrue(df["sharpe"].is_monotonic_decreasing)


if __name__ == "__main__":
    unittest.main()

