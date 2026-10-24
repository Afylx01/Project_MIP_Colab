"""
tests/test_benchmark_selection.py - Comprehensive Unit & Contract Tests for Universal Benchmark Selection
Validates:
1. Benchmark Resolver catalog, normalization, continuous indicators, and synthetic proxy generation.
2. MomentumScanner & HardenedScanner benchmark integration.
3. LightweightBacktester benchmark integration.
4. BruteForceCampaignRunner benchmark propagation, caching, and progress telemetry callback.
5. CLI argument parser and dashboard widget options.
"""

import unittest
import sys
import shutil
import tempfile
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.benchmark_validator import (
    BENCHMARK_CATALOG,
    normalize_benchmark_name,
    get_benchmark_display_options,
    resolve_benchmark_series,
)
from core.scanner import MomentumScanner
from scripts.scanner_hardening import HardenedScanner
from core.backtest import LightweightBacktester
from brute_force.runner import BruteForceCampaignRunner


class TestBenchmarkSelection(unittest.TestCase):
    """Universal Benchmark Selection & Telemetry Contract Tests."""

    def test_01_benchmark_catalog_and_options(self):
        """Verify standard catalog and widget display options."""
        self.assertIn("NIFTY500", BENCHMARK_CATALOG)
        self.assertIn("NIFTY50", BENCHMARK_CATALOG)
        self.assertIn("NIFTY750", BENCHMARK_CATALOG)
        self.assertIn("NIFTYBANK", BENCHMARK_CATALOG)
        self.assertIn("NIFTYIT", BENCHMARK_CATALOG)
        self.assertIn("UNIVERSE_PROXY", BENCHMARK_CATALOG)

        options = get_benchmark_display_options()
        self.assertTrue(len(options) >= 8)
        keys = [opt[1] for opt in options]
        self.assertIn("NIFTY500", keys)
        self.assertIn("NIFTY50", keys)
        self.assertIn("NIFTYBANK", keys)

    def test_02_benchmark_name_normalization(self):
        """Verify alias and code normalization to canonical benchmark IDs."""
        self.assertEqual(normalize_benchmark_name(None), "NIFTY500")
        self.assertEqual(normalize_benchmark_name(""), "NIFTY500")
        self.assertEqual(normalize_benchmark_name("500"), "NIFTY500")
        self.assertEqual(normalize_benchmark_name("NIFTY 50"), "NIFTY50")
        self.assertEqual(normalize_benchmark_name("^NSEI"), "NIFTY50")
        self.assertEqual(normalize_benchmark_name("bank"), "NIFTYBANK")
        self.assertEqual(normalize_benchmark_name("BANKNIFTY"), "NIFTYBANK")
        self.assertEqual(normalize_benchmark_name("^NSEBANK"), "NIFTYBANK")
        self.assertEqual(normalize_benchmark_name("IT"), "NIFTYIT")
        self.assertEqual(normalize_benchmark_name("proxy"), "UNIVERSE_PROXY")
        self.assertEqual(normalize_benchmark_name("RELIANCE"), "RELIANCE")

    def test_03_benchmark_resolver_continuous_series(self):
        """Verify resolution of continuous series and indicator calculation."""
        df_500 = resolve_benchmark_series("NIFTY500", base_dir=PROJECT_ROOT)
        self.assertIsInstance(df_500, pd.DataFrame)
        self.assertFalse(df_500.empty)
        for col in ["date", "close", "daily_return", "ret_252", "ema_20", "ema_50", "ema_200", "high_252", "drawdown"]:
            self.assertIn(col, df_500.columns)

        df_50 = resolve_benchmark_series("NIFTY50", base_dir=PROJECT_ROOT)
        self.assertIsInstance(df_50, pd.DataFrame)
        self.assertFalse(df_50.empty)
        self.assertTrue((df_50["close"] > 0).all())

        df_proxy = resolve_benchmark_series("UNIVERSE_PROXY", base_dir=PROJECT_ROOT)
        self.assertIsInstance(df_proxy, pd.DataFrame)
        self.assertFalse(df_proxy.empty)
        self.assertTrue((df_proxy["close"] > 0).all())

    def test_04_scanner_benchmark_integration(self):
        """Verify scanner accepts and applies custom benchmark."""
        csv_path = PROJECT_ROOT / "reports" / "screener_output_live.csv"
        csv_backup = csv_path.read_bytes() if csv_path.exists() else None

        try:
            scanner = MomentumScanner(base_dir=PROJECT_ROOT, benchmark="NIFTY50")
            self.assertEqual(scanner.benchmark_name, "NIFTY50")
            bm_df = scanner.load_benchmark()
            self.assertIsNotNone(bm_df)
            self.assertFalse(bm_df.empty)

            # Run scan with NIFTY50 benchmark on recent session
            top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(
                as_of_date="2026-10-14",
                universe_mode="NIFTY50",
                top_n=5,
                benchmark="NIFTY50",
                allow_stale_data=True,
            )
            self.assertIsInstance(top_df, pd.DataFrame)
            self.assertEqual(top_df.attrs.get("benchmark_name"), "NIFTY50")
            self.assertIn("benchmark_name", regime)
            self.assertEqual(regime["benchmark_name"], "NIFTY50")
        finally:
            if csv_backup is not None:
                csv_path.write_bytes(csv_backup)

    def test_05_backtester_benchmark_integration(self):
        """Verify LightweightBacktester runs with custom benchmark."""
        output_dir = Path(tempfile.mkdtemp(prefix="mip_bench_bt_"))
        self.addCleanup(shutil.rmtree, output_dir, True)
        bt = LightweightBacktester(base_dir=PROJECT_ROOT, benchmark="NIFTY50", output_dir=output_dir)
        self.assertEqual(bt.benchmark_name, "NIFTY50")
        res = bt.run(start_date="2024-01-01", end_date="2024-12-31", top_n=10)
        self.assertIn("benchmark_name", res)
        self.assertEqual(res["benchmark_name"], "NIFTY50")
        self.assertIn("benchmark_cagr_pct", res)

    def test_06_brute_force_runner_benchmark_and_telemetry(self):
        """Verify BruteForceCampaignRunner benchmark propagation and progress callback."""
        runner = BruteForceCampaignRunner()
        res = runner.run_baseline(
            start_date="2024-01-01",
            end_date="2024-12-31",
            schedule="monthly",
            benchmark="NIFTY50",
        )
        self.assertEqual(res["benchmark"], "NIFTY50")
        self.assertIn("ending_equity", res)

        # Verify progress callback invocation
        progress_events = []

        def dummy_callback(completed, total, speed, elapsed, eta):
            progress_events.append((completed, total, speed, elapsed, eta))

        # Test small sweep with callback
        df = runner.run_custom_sweep(
            lookbacks=[252],
            ema_trends=[200],
            top_ns=[20],
            retrace_thresholds=[0.80],
            schedules=["monthly"],
            start_date="2024-01-01",
            end_date="2024-06-30",
            universe_name="ALL",
            benchmark="NIFTY50",
            progress_callback=dummy_callback,
        )
        self.assertFalse(df.empty)
        self.assertTrue(len(progress_events) >= 1)
        last_event = progress_events[-1]
        self.assertEqual(last_event[0], last_event[1]) # completed == total

    def test_07_cli_parser_benchmark_flag(self):
        """Verify CLI argument parser includes --benchmark."""
        from main import build_parser
        parser = build_parser()
        args = parser.parse_args(["--benchmark", "NIFTYBANK", "--universe", "NIFTYBANK"])
        self.assertEqual(args.benchmark, "NIFTYBANK")
        self.assertEqual(args.universe, "NIFTYBANK")


if __name__ == "__main__":
    unittest.main(verbosity=2)
