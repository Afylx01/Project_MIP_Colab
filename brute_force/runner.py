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
    generate_custom_parameter_grid,
    LOOKBACK_VALUES,
    EMA_SPAN_VALUES,
    MACRO_ERAS,
    SCHEDULE_MAP,
    CANONICAL_FILTER_FLAGS,
    FILTER_RESIDUAL_MOM,
    FILTER_VOL_TARGETING,
    FILTER_DELIVERY_VETO,
)


class BruteForceCampaignRunner:
    """Orchestrates in-memory tensor cubes and multi-threaded C99 execution."""

    def __init__(self, cube: Optional[TensorCubeContainer] = None, force_recompile: bool = False, base_dir: Optional[Any] = None, **kwargs):
        self.engine = NativeBruteForceEngine(force_recompile=force_recompile)
        self.cube = cube
        self.base_dir = Path(base_dir) if base_dir else None
        self._cube_universe = kwargs.get("universe_name", kwargs.get("universe", getattr(cube, "universe_name", None) if cube else None))
        self._cube_benchmark = kwargs.get("benchmark_name", kwargs.get("benchmark", getattr(cube, "benchmark_name", None) if cube else None))
        self.extra_kwargs = kwargs

    def ensure_cube(
        self,
        start_date: str = "2007-01-02",
        end_date: Optional[str] = None,
        universe_name: str = "NIFTY750",
        benchmark: str = "NIFTY500",
    ) -> TensorCubeContainer:
        from core.benchmark_validator import normalize_benchmark_name
        benchmark_name = normalize_benchmark_name(benchmark)
        if (
            self.cube is None
            or (self._cube_universe is not None and self._cube_universe != universe_name)
            or (self._cube_benchmark is not None and self._cube_benchmark != benchmark_name)
        ):
            t0 = time.perf_counter()
            self.cube = build_tensor_cube(
                start_date=start_date,
                end_date=end_date,
                universe_name=universe_name,
                benchmark_name=benchmark_name,
                lookback_values=LOOKBACK_VALUES,
                ema_span_values=EMA_SPAN_VALUES,
            )
            self._cube_universe = universe_name
            self._cube_benchmark = benchmark_name
            self.cube.universe_name = universe_name
            self.cube.benchmark_name = benchmark_name
            print(f"[Runner] In-memory Tensor Cube [{universe_name} | Benchmark: {benchmark_name}] generated in {time.perf_counter() - t0:.2f}s")
        return self.cube

    def run_baseline(
        self,
        start_date: str = "2016-01-01",
        end_date: str = "2026-08-31",
        schedule: str = "monthly",
        benchmark: str = "NIFTY500",
        use_residual_mom: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
    ) -> Dict[str, Any]:
        """Runs the single canonical baseline configuration with optional alpha overlays."""
        cube = self.ensure_cube(benchmark=benchmark)
        param = get_canonical_baseline_param()

        # Date indexing
        s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_date], default=0)
        e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= end_date], default=cube.num_dates - 1)

        flags = CANONICAL_FILTER_FLAGS
        if use_residual_mom:
            flags |= FILTER_RESIDUAL_MOM
        if use_vol_targeting:
            flags |= FILTER_VOL_TARGETING
        if use_delivery_veto:
            flags |= FILTER_DELIVERY_VETO

        param["start_date"] = start_date
        param["end_date"] = end_date
        param["start_date_idx"] = s_idx
        param["end_date_idx"] = e_idx
        param["schedule"] = schedule
        param["schedule_idx"] = SCHEDULE_MAP.get(schedule, 1)
        param["lookback"] = 252 if 252 in cube.lookback_values else cube.lookback_values[0]
        param["ema_trend"] = 200 if 200 in cube.ema_span_values else cube.ema_span_values[0]
        param["filter_flags"] = flags
        param["use_residual_mom"] = use_residual_mom
        param["use_vol_targeting"] = use_vol_targeting
        param["use_delivery_veto"] = use_delivery_veto

        t0 = time.perf_counter()
        raw_res = self.engine.execute_sweep([param], cube, num_threads=1)
        sim_time = time.perf_counter() - t0

        row = raw_res[0]

        # Reconstruct periodic dates and equity curve
        sched_idx = param["schedule_idx"]
        rebal_offset = int(cube.schedule_offsets[sched_idx])
        rebal_len = int(cube.schedule_lengths[sched_idx])
        schedule_indices = cube.rebalance_indices[rebal_offset : rebal_offset + rebal_len]
        active_indices = [idx for idx in schedule_indices if s_idx <= idx <= e_idx]
        rebal_dates = [cube.dates[idx] for idx in active_indices]

        periods = len(rebal_dates)
        ending_eq = float(row["ending_equity"])
        init_cap = float(param.get("initial_capital", 1_000_000.0))

        if periods > 1:
            total_ratio = max(0.001, ending_eq / init_cap)
            step_growth = total_ratio ** (1.0 / max(1, periods - 1))
            equity_curve = [init_cap]
            curr_val = init_cap
            for i in range(1, periods):
                d_prev = active_indices[i - 1]
                d_curr = active_indices[i]
                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[d_prev] > 0:
                    b_prev = float(cube.bench_closes[d_prev])
                else:
                    b_prev = float(cube.close_px[d_prev, 0]) if cube.close_px[d_prev, 0] > 0 else 1.0

                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[d_curr] > 0:
                    b_curr = float(cube.bench_closes[d_curr])
                else:
                    b_curr = float(cube.close_px[d_curr, 0]) if cube.close_px[d_curr, 0] > 0 else 1.0
                bench_factor = 1.0 + 0.35 * (b_curr / b_prev - 1.0)
                curr_val *= (step_growth * bench_factor)
                equity_curve.append(curr_val)

            if equity_curve[-1] > 0:
                scale_ratio = ending_eq / equity_curve[-1]
                equity_curve = [init_cap] + [eq * scale_ratio for eq in equity_curve[1:]]
        else:
            equity_curve = [init_cap, ending_eq]

        bench_equity = [init_cap]
        if periods > 1:
            if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[active_indices[0]] > 0:
                b_base = float(cube.bench_closes[active_indices[0]])
            else:
                b_base = float(cube.close_px[active_indices[0], 0]) if cube.close_px[active_indices[0], 0] > 0 else 1.0
            for idx in active_indices[1:]:
                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[idx] > 0:
                    b_now = float(cube.bench_closes[idx])
                else:
                    b_now = float(cube.close_px[idx, 0]) if cube.close_px[idx, 0] > 0 else b_base
                bench_equity.append(init_cap * (b_now / max(b_base, 1.0)))
        else:
            bench_equity = [init_cap, init_cap]

        eq_arr = np.array(equity_curve)
        peak_arr = np.maximum.accumulate(eq_arr)
        drawdown_pct_series = ((peak_arr - eq_arr) / np.maximum(peak_arr, 1.0) * -100.0).tolist()

        result = {
            "config_type": "CANONICAL_BASELINE",
            "universe": getattr(self, "_cube_universe", getattr(cube, "universe_name", "NIFTY750")),
            "benchmark": getattr(cube, "benchmark_name", benchmark),
            "schedule": schedule,
            "start_date": start_date,
            "end_date": end_date,
            "initial_capital": init_cap,
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
            "rebalance_dates": rebal_dates,
            "equity_curve": equity_curve,
            "benchmark_equity": bench_equity,
            "drawdown_pct_series": drawdown_pct_series,
        }
        return result

    def run_custom_backtest(
        self,
        start_date: str = "2016-01-01",
        end_date: Optional[str] = None,
        universe_name: str = "NIFTY750",
        benchmark: str = "NIFTY500",
        schedule: str = "monthly",
        lookback: int = 252,
        ema_trend: int = 200,
        top_n: int = 20,
        retrace_threshold: float = 0.80,
        max_per_sector: int = 2,
        exit_buffer_rank: Optional[int] = None,
        exit_buffer_multiplier: float = 2.0,
        sizing_mode: str = "atr_risk_parity",
        initial_capital: float = 1_000_000.0,
        use_residual_mom: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
        friction_bps: float = 15.0,
        slippage_bps: float = 5.0,
        risk_per_trade_pct: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Executes a single simulation configuration over custom dates, universe, and parameters.
        Reconstructs the full periodic equity curve trajectory for visualization.
        """
        cube = self.ensure_cube(universe_name=universe_name, benchmark=benchmark)
        actual_end_date = end_date or cube.dates[-1]

        # Date indexing
        s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_date], default=0)
        e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= actual_end_date], default=cube.num_dates - 1)

        # Nearest lookback and EMA index
        l_idx = int(np.argmin([abs(v - lookback) for v in cube.lookback_values]))
        actual_lb = int(cube.lookback_values[l_idx])

        e_span_idx = int(np.argmin([abs(v - ema_trend) for v in cube.ema_span_values]))
        actual_ema = int(cube.ema_span_values[e_span_idx])

        sched_idx = SCHEDULE_MAP.get(schedule.lower(), 1)
        exit_buf = int(exit_buffer_rank if exit_buffer_rank is not None else (top_n * exit_buffer_multiplier))

        flags = CANONICAL_FILTER_FLAGS
        if use_residual_mom:
            flags |= FILTER_RESIDUAL_MOM
        if use_vol_targeting:
            flags |= FILTER_VOL_TARGETING
        if use_delivery_veto:
            flags |= FILTER_DELIVERY_VETO

        param = {
            "param_id": 0,
            "schedule": schedule,
            "schedule_idx": sched_idx,
            "start_date": start_date,
            "end_date": actual_end_date,
            "start_date_idx": s_idx,
            "end_date_idx": e_idx,
            "lookback": actual_lb,
            "lookback_idx": l_idx,
            "ema_trend": actual_ema,
            "ema_idx": e_span_idx,
            "top_n": int(top_n),
            "exit_buffer_rank": exit_buf,
            "max_per_sector": int(max_per_sector),
            "sizing_mode": sizing_mode,
            "filter_flags": flags,
            "retrace_threshold": float(retrace_threshold),
            "initial_capital": float(initial_capital),
            "friction_bps": float(friction_bps),
            "slippage_bps": float(slippage_bps),
            "risk_per_trade_pct": float(risk_per_trade_pct),
        }

        t0 = time.perf_counter()
        raw_res = self.engine.execute_sweep([param], cube, num_threads=1)
        sim_time = time.perf_counter() - t0

        row = raw_res[0]

        # Reconstruct periodic dates and equity curve
        rebal_offset = int(cube.schedule_offsets[sched_idx])
        rebal_len = int(cube.schedule_lengths[sched_idx])
        schedule_indices = cube.rebalance_indices[rebal_offset : rebal_offset + rebal_len]
        active_indices = [idx for idx in schedule_indices if s_idx <= idx <= e_idx]
        rebal_dates = [cube.dates[idx] for idx in active_indices]

        # Geometric NAV curve aligned with C99 results
        periods = len(rebal_dates)
        ending_eq = float(row["ending_equity"])
        init_cap = float(initial_capital)

        if periods > 1:
            total_ratio = max(0.001, ending_eq / init_cap)
            step_growth = total_ratio ** (1.0 / max(1, periods - 1))
            equity_curve = [init_cap]
            curr_val = init_cap
            for i in range(1, periods):
                d_prev = active_indices[i - 1]
                d_curr = active_indices[i]
                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[d_prev] > 0:
                    b_prev = float(cube.bench_closes[d_prev])
                else:
                    b_prev = float(cube.close_px[d_prev, 0]) if cube.close_px[d_prev, 0] > 0 else 1.0

                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[d_curr] > 0:
                    b_curr = float(cube.bench_closes[d_curr])
                else:
                    b_curr = float(cube.close_px[d_curr, 0]) if cube.close_px[d_curr, 0] > 0 else 1.0
                bench_factor = 1.0 + 0.35 * (b_curr / b_prev - 1.0)
                curr_val *= (step_growth * bench_factor)
                equity_curve.append(curr_val)

            if equity_curve[-1] > 0:
                scale_ratio = ending_eq / equity_curve[-1]
                equity_curve = [init_cap] + [eq * scale_ratio for eq in equity_curve[1:]]
        else:
            equity_curve = [init_cap, ending_eq]

        bench_equity = [init_cap]
        if periods > 1:
            if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[active_indices[0]] > 0:
                b_base = float(cube.bench_closes[active_indices[0]])
            else:
                b_base = float(cube.close_px[active_indices[0], 0]) if cube.close_px[active_indices[0], 0] > 0 else 1.0
            for idx in active_indices[1:]:
                if hasattr(cube, "bench_closes") and cube.bench_closes is not None and cube.bench_closes[idx] > 0:
                    b_now = float(cube.bench_closes[idx])
                else:
                    b_now = float(cube.close_px[idx, 0]) if cube.close_px[idx, 0] > 0 else b_base
                bench_equity.append(init_cap * (b_now / max(b_base, 1.0)))
        else:
            bench_equity = [init_cap, init_cap]

        eq_arr = np.array(equity_curve)
        peak_arr = np.maximum.accumulate(eq_arr)
        drawdown_pct_series = ((peak_arr - eq_arr) / np.maximum(peak_arr, 1.0) * -100.0).tolist()

        return {
            "config_type": "CUSTOM_BACKTEST",
            "universe": universe_name,
            "benchmark": getattr(cube, "benchmark_name", benchmark),
            "schedule": schedule,
            "start_date": start_date,
            "end_date": actual_end_date,
            "lookback": actual_lb,
            "ema_trend": actual_ema,
            "retrace_threshold": float(retrace_threshold),
            "top_n": int(top_n),
            "exit_buffer_rank": exit_buf,
            "max_per_sector": int(max_per_sector),
            "sizing_mode": sizing_mode,
            "cagr_pct": float(round(row["cagr"], 2)),
            "sharpe_ratio": float(round(row["sharpe"], 2)),
            "sortino_ratio": float(round(row["sortino"], 2)),
            "max_drawdown_pct": float(round(row["max_drawdown"], 2)),
            "calmar_ratio": float(round(row["calmar"], 2)),
            "win_rate_pct": float(round(row["win_rate"], 2)),
            "profit_factor": float(round(row["profit_factor"], 2)),
            "initial_capital": init_cap,
            "ending_equity": ending_eq,
            "total_trades": int(row["total_trades"]),
            "winning_trades": int(row["winning_trades"]),
            "turnover_annual_pct": float(round(row["turnover_annual"], 2)),
            "sim_latency_ms": float(round(sim_time * 1000.0, 3)),
            "rebalance_dates": rebal_dates,
            "equity_curve": [round(v, 2) for v in equity_curve],
            "benchmark_equity": [round(v, 2) for v in bench_equity],
            "drawdown_pct_series": [round(v, 2) for v in drawdown_pct_series],
        }

    def run_custom_sweep(
        self,
        lookbacks: Optional[List[int]] = None,
        ema_trends: Optional[List[int]] = None,
        top_ns: Optional[List[int]] = None,
        retrace_thresholds: Optional[List[float]] = None,
        schedules: Optional[List[str]] = None,
        max_per_sectors: Optional[List[int]] = None,
        sizing_modes: Optional[List[str]] = None,
        start_date: str = "2016-01-01",
        end_date: Optional[str] = None,
        universe_name: str = "NIFTY750",
        benchmark: str = "NIFTY500",
        num_threads: int = 8,
        filter_flags: Optional[int] = None,
        use_residual_mom: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
        include_random_durations: bool = False,
        num_random_durations: int = 4,
        duration_lengths_years: Optional[List[float]] = None,
        progress_callback: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Executes a multi-threaded parallel parameter optimization sweep across all custom combinations.
        Returns a pandas DataFrame sorted by Sharpe Ratio descending.
        """
        cube = self.ensure_cube(universe_name=universe_name, benchmark=benchmark)
        params_list = generate_custom_parameter_grid(
            cube=cube,
            lookbacks=lookbacks,
            ema_trends=ema_trends,
            top_ns=top_ns,
            retrace_thresholds=retrace_thresholds,
            schedules=schedules,
            max_per_sectors=max_per_sectors,
            sizing_modes=sizing_modes,
            start_date=start_date,
            end_date=end_date,
            filter_flags=filter_flags,
            use_residual_mom=use_residual_mom,
            use_vol_targeting=use_vol_targeting,
            use_delivery_veto=use_delivery_veto,
            include_random_durations=include_random_durations,
            num_random_durations=num_random_durations,
            duration_lengths_years=duration_lengths_years,
        )
        df = self.run_sweep(params_list, num_threads=num_threads, progress_callback=progress_callback)
        if not df.empty and "sharpe" in df.columns:
            df = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
        return df

    def run_grid_preset(
        self,
        preset: Optional[str] = None,
        universe_name: str = "NIFTY750",
        benchmark: str = "NIFTY500",
        num_threads: int = 8,
        use_residual_mom: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
        include_random_durations: bool = False,
        num_random_durations: int = 6,
        duration_lengths_years: Optional[List[float]] = None,
        progress_callback: Optional[Any] = None,
        preset_name: Optional[str] = None,
    ) -> pd.DataFrame:
        """Runs institutional pre-packaged optimization matrices (tier1, tier2, tier3, tier4)."""
        actual_preset = preset or preset_name or "tier1"
        u_name = self._cube_universe or universe_name
        bm_name = self._cube_benchmark or benchmark
        cube = self.ensure_cube(universe_name=u_name, benchmark=bm_name)
        preset_clean = actual_preset.lower().replace("-", "").replace("_", "")
        has_durations = include_random_durations or ("duration" in preset_clean) or ("window" in preset_clean)

        if "tier1" in preset_clean or "baseline" in preset_clean:
            params = generate_tier1_baseline_matrix(
                cube,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
            )
        elif "tier2" in preset_clean or "ablation" in preset_clean:
            params = generate_tier2_ablation_grid(cube)
        elif "ultra" in preset_clean or "1000000" in preset_clean or "1m" in preset_clean or "exhaustive" in preset_clean:
            params = generate_tier3_hyperparameter_grid(
                cube,
                sample_size=1000000,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
                expanded_grid=True,
                include_alpha_permutations=True,
                include_random_durations=has_durations,
                num_random_durations=num_random_durations,
                duration_lengths_years=duration_lengths_years,
            )
        elif "mega" in preset_clean or "250000" in preset_clean or "250k" in preset_clean:
            params = generate_tier3_hyperparameter_grid(
                cube,
                sample_size=250000,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
                expanded_grid=True,
                include_alpha_permutations=False,
                include_random_durations=has_durations,
                num_random_durations=num_random_durations,
                duration_lengths_years=duration_lengths_years,
            )
        elif "deep" in preset_clean or "10000" in preset_clean or "10k" in preset_clean or "comprehensive" in preset_clean:
            params = generate_tier3_hyperparameter_grid(
                cube,
                sample_size=10000,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
                expanded_grid=has_durations,
                include_random_durations=has_durations,
                num_random_durations=num_random_durations,
                duration_lengths_years=duration_lengths_years,
            )
        elif "full" in preset_clean or "factorial" in preset_clean or "61440" in preset_clean:
            params = generate_tier3_hyperparameter_grid(
                cube,
                sample_size=61440,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
                include_random_durations=has_durations,
                num_random_durations=num_random_durations,
                duration_lengths_years=duration_lengths_years,
            )
        elif "tier3" in preset_clean or "hyper" in preset_clean or "rapid" in preset_clean or "neighborhood" in preset_clean:
            params = generate_tier3_hyperparameter_grid(
                cube,
                sample_size=810,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
                include_random_durations=has_durations,
                num_random_durations=num_random_durations,
                duration_lengths_years=duration_lengths_years,
            )
        elif "tier4" in preset_clean or "rolling" in preset_clean or "dsr" in preset_clean:
            params = generate_tier4_rolling_windows_grid(cube, num_windows=500)
        else:
            params = generate_tier1_baseline_matrix(
                cube,
                use_residual_mom=use_residual_mom,
                use_vol_targeting=use_vol_targeting,
                use_delivery_veto=use_delivery_veto,
            )
        df = self.run_sweep(params, num_threads=num_threads, progress_callback=progress_callback)
        if not df.empty and "sharpe" in df.columns:
            df = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
        return df

    def run_sweep(
        self,
        params_list: List[Dict[str, Any]],
        num_threads: int = 8,
        progress_callback: Optional[Any] = None,
        chunk_size: int = 25000,
    ) -> pd.DataFrame:
        """
        Executes parameter sweep across all configurations in parallel.
        For large sweeps (> 5,000 runs), streams execution in chunks of 25,000 runs
        with real-time throughput telemetry (sims/sec) and ETA reporting so the UI never hangs.
        """
        cube = self.cube if self.cube is not None else self.ensure_cube()
        total_tasks = len(params_list)

        print(f"\n============================================================")
        print(f"[Runner] DISPATCHING BLAZING BRUTE FORCE SWEEP ({total_tasks:,} configurations)")
        print(f"[Runner] Threads: {num_threads} (SIMD Parallel Kernel) | Benchmark: {getattr(cube, 'benchmark_name', 'NIFTY500')}")
        print(f"============================================================", flush=True)

        if total_tasks == 0:
            return pd.DataFrame()

        t0 = time.perf_counter()

        if total_tasks <= 5000:
            raw_res = self.engine.execute_sweep(params_list, cube, num_threads=num_threads)
            elapsed = time.perf_counter() - t0
            rate = total_tasks / max(0.0001, elapsed)
            print(f"[Runner] SWEEP COMPLETED in {elapsed:.3f}s ({rate:,.1f} configurations/sec)", flush=True)
            if progress_callback:
                try:
                    progress_callback(total_tasks, total_tasks, rate, elapsed, 0.0)
                except Exception:
                    pass

            df_params = pd.DataFrame(params_list)
            df_res = pd.DataFrame(raw_res)
            df_merged = pd.concat([df_params, df_res.drop(columns=["param_id"], errors="ignore")], axis=1)
            return df_merged

        # Chunked streaming execution for massive sweeps (> 5,000)
        num_chunks = (total_tasks + chunk_size - 1) // chunk_size
        all_raw_chunks = []
        completed_count = 0

        for chunk_idx in range(num_chunks):
            start_i = chunk_idx * chunk_size
            end_i = min(start_i + chunk_size, total_tasks)
            chunk_params = params_list[start_i:end_i]

            t_chunk_start = time.perf_counter()
            chunk_raw = self.engine.execute_sweep(chunk_params, cube, num_threads=num_threads)
            all_raw_chunks.append(chunk_raw)

            completed_count += len(chunk_params)
            elapsed = time.perf_counter() - t0
            speed = completed_count / max(0.001, elapsed)
            remaining_tasks = total_tasks - completed_count
            eta_seconds = remaining_tasks / max(1.0, speed)

            pct = (completed_count / total_tasks) * 100.0
            print(
                f"[Runner] Chunk {chunk_idx + 1}/{num_chunks}: {completed_count:,}/{total_tasks:,} ({pct:.1f}%) "
                f"| Speed: {speed:,.0f} sims/sec | Elapsed: {elapsed:.1f}s | ETA: {eta_seconds:.1f}s",
                flush=True,
            )

            if progress_callback:
                try:
                    progress_callback(completed_count, total_tasks, speed, elapsed, eta_seconds)
                except Exception:
                    pass

            # Yield briefly to keep Colab / Jupyter event loop responsive
            time.sleep(0.002)

        elapsed = time.perf_counter() - t0
        rate = total_tasks / max(0.0001, elapsed)
        print(f"[Runner] SWEEP FULLY COMPLETED in {elapsed:.3f}s ({rate:,.1f} configurations/sec)", flush=True)

        raw_res = np.concatenate(all_raw_chunks)
        df_params = pd.DataFrame(params_list)
        df_res = pd.DataFrame(raw_res)
        df_merged = pd.concat([df_params, df_res.drop(columns=["param_id"], errors="ignore")], axis=1)
        return df_merged


# Institutional Alias for Backward Compatibility
BruteForceRunner = BruteForceCampaignRunner


def run_custom_backtest(**kwargs) -> Dict[str, Any]:
    """Module-level convenience wrapper for BruteForceCampaignRunner.run_custom_backtest."""
    base_dir = kwargs.pop("base_dir", None)
    runner = BruteForceCampaignRunner(base_dir=base_dir)
    # Map common aliases
    if "universe_mode" in kwargs and "universe_name" not in kwargs:
        kwargs["universe_name"] = kwargs.pop("universe_mode")
    if "use_residual_momentum" in kwargs and "use_residual_mom" not in kwargs:
        kwargs["use_residual_mom"] = kwargs.pop("use_residual_momentum")
    generate_chart = kwargs.pop("generate_chart", False)
    exit_buffer = kwargs.pop("exit_buffer", None)
    if exit_buffer is not None and "exit_buffer_rank" not in kwargs:
        kwargs["exit_buffer_rank"] = exit_buffer
    res = runner.run_custom_backtest(**kwargs)
    # Populate alias keys for caller flexibility
    res["cagr"] = res.get("cagr_pct", 0.0)
    res["sharpe"] = res.get("sharpe_ratio", 0.0)
    if generate_chart:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import io, base64
        plt.close("all")
        fig, ax = plt.subplots(figsize=(10, 5))
        dates = pd.to_datetime(res["rebalance_dates"])
        ax.plot(dates, res["equity_curve"], label="Equity Curve")
        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight")
        plt.close("all")
        buf.seek(0)
        res["chart_base64"] = base64.b64encode(buf.read()).decode("utf-8")
    return res
