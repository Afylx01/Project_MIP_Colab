"""
MIP Android — Main Application Brute Force Optimizer & Strategy Matrix Integration Tests
Validates that main.py exposes Option [18], CLI arguments (--option 18, --brute-force, --brute-force-mode,
--schedule, --top-n, --sizing-mode), interactive and non-interactive execution pathways, and C99 NEON
engine integration.
"""

import unittest
import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestMainBruteForceIntegration(unittest.TestCase):
    """Test CLI argument parsing and Option 18 brute-force integration in main.py."""

    def test_main_cli_parser_accepts_brute_force_flags(self):
        """Verify main.py argument parser accepts --brute-force and related arguments."""
        import main
        parser = main.build_parser() if hasattr(main, "build_parser") else None
        self.assertIsNotNone(parser, "main.py must expose build_parser() function")

        # Option 18
        args = parser.parse_args(["--option", "18"])
        self.assertEqual(args.option, 18)

        # --brute-force flag
        args = parser.parse_args(["--brute-force"])
        self.assertTrue(args.brute_force)

        # --brute-force-mode choices
        for mode in ["baseline", "tier1", "tier2", "comprehensive", "matrix"]:
            args = parser.parse_args(["--brute-force", "--brute-force-mode", mode])
            self.assertEqual(args.brute_force_mode, mode)

        # --schedule choices
        for sched in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]:
            args = parser.parse_args(["--brute-force", "--schedule", sched])
            self.assertEqual(args.schedule, sched)

        # --top-n and --sizing-mode
        args = parser.parse_args(["--brute-force", "--top-n", "10", "--sizing-mode", "equal_weight"])
        self.assertEqual(args.top_n, 10)
        self.assertEqual(args.sizing_mode, "equal_weight")

    def test_main_exposes_run_brute_force_flow(self):
        """Verify main.py defines and exposes run_brute_force_flow as a callable."""
        import main
        self.assertTrue(hasattr(main, "run_brute_force_flow"),
                        "main.py must define run_brute_force_flow function")
        self.assertTrue(callable(main.run_brute_force_flow))

    def test_run_brute_force_flow_non_interactive_baseline_execution(self):
        """Verify run_brute_force_flow executes baseline simulation cleanly in non-interactive mode."""
        import main
        res = main.run_brute_force_flow(
            interactive=False,
            mode="baseline",
            schedule="monthly",
            universe_mode="NIFTY50",
            start_date="2020-01-01",
            end_date="2021-12-31",
        )
        self.assertIsInstance(res, dict, "run_brute_force_flow baseline must return summary dict")
        self.assertIn("cagr_pct", res)
        self.assertIn("sharpe_ratio", res)
        self.assertIn("max_drawdown_pct", res)
        self.assertIn("total_trades", res)
        self.assertEqual(res["schedule"], "monthly")
        self.assertGreater(res["sim_latency_ms"], 0.0)

    def test_run_brute_force_flow_weekly_schedule_execution(self):
        """Verify run_brute_force_flow executes weekly schedule baseline simulation."""
        import main
        res = main.run_brute_force_flow(
            interactive=False,
            mode="baseline",
            schedule="weekly",
            universe_mode="NIFTY50",
            start_date="2020-01-01",
            end_date="2020-12-31",
        )
        self.assertIsInstance(res, dict)
        self.assertEqual(res["schedule"], "weekly")
        self.assertGreater(res["total_trades"], 0)

    def test_run_brute_force_flow_tier1_matrix_execution(self):
        """Verify run_brute_force_flow executes Tier 1 baseline matrix in non-interactive mode."""
        import main
        df = main.run_brute_force_flow(
            interactive=False,
            mode="tier1",
            universe_mode="NIFTY50",
        )
        import pandas as pd
        self.assertIsInstance(df, pd.DataFrame, "Tier 1 matrix must return a pandas DataFrame")
        self.assertEqual(len(df), 35, "Tier 1 matrix must evaluate exactly 35 configurations (7 Eras x 5 Schedules)")
        self.assertIn("cagr", df.columns)
        self.assertIn("sharpe", df.columns)
        self.assertIn("schedule", df.columns)

    def test_brute_force_with_optional_alpha_overlays(self):
        """Verify brute force baseline runs with residual momentum, vol targeting, and delivery veto."""
        import main
        res = main.run_brute_force_flow(
            interactive=False,
            mode="baseline",
            schedule="monthly",
            universe_mode="NIFTY50",
            start_date="2020-01-01",
            end_date="2021-12-31",
            use_residual_momentum=True,
            use_vol_targeting=True,
            use_delivery_veto=True,
        )
        self.assertIsInstance(res, dict)
        self.assertIn("cagr_pct", res)
        self.assertIn("sharpe_ratio", res)
        self.assertGreater(res["ending_equity"], 0.0)

    def test_custom_sweep_with_optional_alphas(self):
        """Verify BruteForceCampaignRunner custom sweep accepts and evaluates alpha overlays."""
        from brute_force.runner import BruteForceCampaignRunner
        runner = BruteForceCampaignRunner()
        df = runner.run_custom_sweep(
            lookbacks=[252],
            ema_trends=[200],
            top_ns=[10],
            schedules=["monthly"],
            start_date="2020-01-01",
            end_date="2020-12-31",
            universe_name="NIFTY50",
            num_threads=2,
            use_residual_mom=True,
            use_vol_targeting=True,
            use_delivery_veto=True,
        )
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 1)
        self.assertTrue(df.iloc[0]["use_residual_mom"])
        self.assertTrue(df.iloc[0]["use_vol_targeting"])
        self.assertTrue(df.iloc[0]["use_delivery_veto"])

    def test_generate_tier3_expanded_factorial_grid(self):
        """Verify expanded factorial hyperparameter grid generator produces valid large parameter spaces."""
        from brute_force.grid import generate_tier3_hyperparameter_grid
        from brute_force.runner import BruteForceCampaignRunner
        runner = BruteForceCampaignRunner()
        cube = runner.ensure_cube(universe_name="NIFTY50")

        # Test classic 30,720 matrix
        grid_classic = generate_tier3_hyperparameter_grid(cube, sample_size=30720, expanded_grid=False)
        self.assertEqual(len(grid_classic), 30720)

        # Test expanded 61,440 matrix
        grid_expanded = generate_tier3_hyperparameter_grid(cube, sample_size=61440, expanded_grid=True)
        self.assertEqual(len(grid_expanded), 61440)

        # Test sampled expanded matrix across 1.7M space
        grid_sampled = generate_tier3_hyperparameter_grid(cube, sample_size=1000, expanded_grid=True, include_alpha_permutations=True)
        self.assertEqual(len(grid_sampled), 1000)
        self.assertIn(grid_sampled[0]["schedule"], ["weekly", "monthly", "quarterly", "half_yearly", "yearly"])
        self.assertIn("use_residual_mom", grid_sampled[0])
        self.assertIn("use_vol_targeting", grid_sampled[0])
        self.assertIn("use_delivery_veto", grid_sampled[0])

    def test_generate_random_time_duration_windows(self):
        """Verify random time duration window generator produces valid sub-periods."""
        from brute_force.grid import generate_random_time_duration_windows
        from brute_force.runner import BruteForceCampaignRunner
        runner = BruteForceCampaignRunner()
        cube = runner.ensure_cube(universe_name="NIFTY50")

        windows = generate_random_time_duration_windows(cube, num_durations=6, seed=42)
        self.assertEqual(len(windows), 6)
        for w in windows:
            self.assertIn("start_date_idx", w)
            self.assertIn("end_date_idx", w)
            self.assertIn("start_date", w)
            self.assertIn("end_date", w)
            self.assertIn("duration_years", w)
            self.assertIn("duration_name", w)
            self.assertGreater(w["end_date_idx"], w["start_date_idx"])
            self.assertGreater(w["duration_years"], 0.0)

    def test_generate_tier3_grid_with_random_time_duration_dimension(self):
        """Verify Tier 3 hyperparameter grid incorporates random time duration as an explicit dimension."""
        from brute_force.grid import generate_tier3_hyperparameter_grid
        from brute_force.runner import BruteForceCampaignRunner
        runner = BruteForceCampaignRunner()
        cube = runner.ensure_cube(universe_name="NIFTY50")

        # Sample 50 configurations with random time durations enabled
        grid = generate_tier3_hyperparameter_grid(
            cube,
            sample_size=50,
            expanded_grid=True,
            include_random_durations=True,
            num_random_durations=6,
        )
        self.assertEqual(len(grid), 50)
        p = grid[0]
        self.assertIn("duration_years", p)
        self.assertIn("duration_name", p)
        self.assertIn("start_date_idx", p)
        self.assertIn("end_date_idx", p)
        self.assertIn("era", p)

    def test_sweep_execution_with_random_time_durations(self):
        """Verify sweep execution runs cleanly across random time durations."""
        from brute_force.runner import BruteForceCampaignRunner
        from brute_force.grid import generate_tier3_hyperparameter_grid
        runner = BruteForceCampaignRunner()
        cube = runner.ensure_cube(universe_name="NIFTY50")

        grid = generate_tier3_hyperparameter_grid(
            cube,
            sample_size=5,
            expanded_grid=True,
            include_random_durations=True,
            num_random_durations=4,
        )
        df = runner.run_sweep(grid, num_threads=2)
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 5)
        self.assertIn("duration_years", df.columns)
        self.assertIn("cagr", df.columns)
        self.assertIn("sharpe", df.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)

