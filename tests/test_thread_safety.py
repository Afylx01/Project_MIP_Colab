"""
tests/test_thread_safety.py - Verifies parallel execution work distribution and thread safety.
"""
import unittest
import numpy as np
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.bridge import NativeBruteForceEngine, compile_native_kernel
from brute_force.cube_builder import TensorCubeContainer


class TestThreadSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compile_native_kernel(force_recompile=True)
        cls.engine = NativeBruteForceEngine()

    def test_parallel_work_distribution(self):
        """Verify atomic task counter is shared across threads (not thread-local)."""
        num_dates = 100
        num_symbols = 10
        px = np.ones((num_dates, num_symbols), dtype=np.float32) * 100.0
        dates = [f"2020-01-{i+1:02d}" if i < 31 else f"2020-02-{i-30:02d}" for i in range(num_dates)]
        symbols = [f"SYM_{i}" for i in range(num_symbols)]
        reb = np.array([0, 50, 99], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        cube = TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )

        params = [{
            "param_id": i,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 99,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 5,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 15.0,
            "slippage_bps": 5.0
        } for i in range(64)]

        # Run with 8 threads, verify each param_id appears exactly once in results
        res = self.engine.run_sweep(cube, params, num_threads=8)
        self.assertEqual(len(res), 64)
        self.assertEqual(res["param_id"].nunique(), 64, "All 64 unique work units must be processed without duplication")


if __name__ == "__main__":
    unittest.main()
