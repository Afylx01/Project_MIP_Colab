"""
runner.py - High-Performance Brute Force Campaign Orchestrator for Project MIP
Optimized for Qualcomm Snapdragon 8 Gen 2 / aarch64 native NEON execution.
"""

import time
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import pandas as pd

from .cube_builder import TensorCubeContainer, build_tensor_cube
from .bridge import NativeBruteForceEngine
from .grid import (
    get_canonical_baseline_param,
    generate_tier1_baseline_matrix,
    generate_tier2_ablation_grid,
    generate_tier3_hyperparameter_grid,
    generate_tier4_rolling_windows_grid,
    LOOKBACK_VALUES,
    EMA_SPAN_VALUES,
    MACRO_ERAS,
)


class BruteForceCampaignRunner:
    """Orchestrates in-memory tensor cubes and multi-threaded C99 execution."""

    def __init__(self, cube: Optional[TensorCubeContainer] = None, force_recompile: bool = False):
        self.engine = NativeBruteForceEngine(force_recompile=force_recompile)
        self.cube = cube

    def ensure_cube(
        self,
        start_date: str = "2007-01-02",
        end_date: str = "2026-10-09",
        universe_name: str = "NIFTY500",
    ) -> TensorCubeContainer:
        if self.cube is None:
            t0 = time.perf_counter()
            self.cube = build_tensor_cube(
                start_date=start_date,
                end_date=end_date,
                universe_name=universe_name,
                lookback_values=LOOKBACK_VALUES,
                ema_span_values=EMA_SPAN_VALUES,
            )
            print(f"[Runner] In-memory Tensor Cube generated in {time.perf_counter() - t0:.2f}s")
        return self.cube

    def run_baseline(
        self,
        start_date: str = "2016-01-01",
        end_date: str = "2026-08-31",
        schedule: str = "monthly",
    ) -> Dict[str, Any]:
        """Runs the single canonical baseline configuration."""
        cube = self.ensure_cube()
        param = get_canonical_baseline_param()

        # Date indexing
        s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_date], default=0)
        e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= end_date], default=cube.num_dates - 1)

        param["start_date"] = start_date
        param["end_date"] = end_date
        param["start_date_idx"] = s_idx
        param["end_date_idx"] = e_idx
        param["schedule"] = schedule
        sched_map = {"weekly": 0, "monthly": 1, "quarterly": 2, "half_yearly": 3, "yearly": 4}
        param["schedule_idx"] = sched_map.get(schedule, 1)

        t0 = time.perf_counter()
        raw_res = self.engine.execute_sweep([param], cube, num_threads=1)
        sim_time = time.perf_counter() - t0

        row = raw_res[0]
        result = {
            "config_type": "CANONICAL_BASELINE",
            "schedule": schedule,
            "start_date": start_date,
            "end_date": end_date,
            "lookback": param["lookback"],
            "ema_trend": param["ema_trend"],
            "retrace_threshold": param["retrace_threshold"],
            "top_n": param["top_n"],
            "exit_buffer_rank": param["exit_buffer_rank"],
            "max_per_sector": param["max_per_sector"],
            "cagr_pct": float(round(row["cagr"], 2)),
            "sharpe_ratio": float(round(row["sharpe"], 2)),
            "sortino_ratio": float(round(row["sortino"], 2)),
            "max_drawdown_pct": float(round(row["max_drawdown"], 2)),
            "calmar_ratio": float(round(row["calmar"], 2)),
            "win_rate_pct": float(round(row["win_rate"], 2)),
            "profit_factor": float(round(row["profit_factor"], 2)),
            "ending_equity": float(round(row["ending_equity"], 2)),
            "total_trades": int(row["total_trades"]),
            "winning_trades": int(row["winning_trades"]),
            "turnover_annual_pct": float(round(row["turnover_annual"], 2)),
            "sim_latency_ms": float(round(sim_time * 1000.0, 3)),
        }
        return result

    def run_sweep(
        self,
        params_list: List[Dict[str, Any]],
        num_threads: int = 8,
    ) -> pd.DataFrame:
        """
        Executes parameter sweep across all configurations in parallel.
        Returns a DataFrame merging parameters with simulation results.
        """
        cube = self.ensure_cube()
        total_tasks = len(params_list)

        print(f"\n============================================================")
        print(f"[Runner] DISPATCHING BLAZING BRUTE FORCE SWEEP ({total_tasks:,} configurations)")
        print(f"[Runner] Threads: {num_threads} (Snapdragon 8 Gen 2 Cortex-X3 + Perf/Eff Cores)")
        print(f"============================================================")

        t0 = time.perf_counter()
        raw_res = self.engine.execute_sweep(params_list, cube, num_threads=num_threads)
        elapsed = time.perf_counter() - t0
        rate = total_tasks / elapsed if elapsed > 0 else 0.0

        print(f"[Runner] SWEEP COMPLETED in {elapsed:.3f}s ({rate:,.1f} configurations/sec)")

        # Merge parameter metadata with metrics
        df_params = pd.DataFrame(params_list)
        df_res = pd.DataFrame(raw_res)

        df_merged = pd.concat([df_params, df_res.drop(columns=["param_id"], errors="ignore")], axis=1)
        return df_merged
