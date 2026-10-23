"""
run_blazing_brute_force.py - High-Performance Brute Force CLI Runner for Project MIP
Targeted for Qualcomm Snapdragon 8 Gen 2 under Termux PRoot Ubuntu Linux.
Upgraded to match and exceed all legacy and next-gen simulation speeds with multi-schedule support.
"""

import sys
import argparse
import time
import json
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (
    get_canonical_baseline_param,
    generate_tier1_baseline_matrix,
    generate_tier2_ablation_grid,
    generate_tier3_hyperparameter_grid,
    CANONICAL_FILTER_FLAGS,
    NEXTGEN_ALL_FLAGS,
)


def main():
    parser = argparse.ArgumentParser(description="Run Blazing Brute Force Optimizer for Project MIP")
    parser.add_argument("--mode", choices=["baseline", "tier1", "tier2", "comprehensive"], default="baseline",
                        help="Execution mode: baseline, tier1 (35 era/schedule runs), tier2 (ablation), or comprehensive grid")
    parser.add_argument("--schedule", choices=["weekly", "monthly", "quarterly", "half_yearly", "yearly"],
                        default="monthly", help="Rebalance schedule frequency")
    parser.add_argument("--universe", type=str, default="NIFTY500", help="Constituent universe name (default NIFTY500)")
    parser.add_argument("--start-date", type=str, default="2016-01-01", help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, default="2026-08-31", help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--top-n", type=int, default=20, help="Portfolio Top N stocks (e.g. 5, 10, 15, 20)")
    parser.add_argument("--sizing-mode", choices=["atr_risk_parity", "equal_weight"], default="atr_risk_parity",
                        help="Position sizing mode")
    parser.add_argument("--threads", type=int, default=8, help="Number of worker threads (default 8 for S23)")
    parser.add_argument("--force-recompile", action="store_true", default=False, help="Force recompilation of C99 kernel")
    parser.add_argument("--output-dir", type=str, default="reports/brute_force", help="Directory for output reports")
    args = parser.parse_args()

    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"╔══════════════════════════════════════════════════════════════════════╗")
    print(f"║       PROJECT MIP: BLAZING FAST BRUTE FORCE SIMULATION ENGINE        ║")
    print(f"║     Snapdragon 8 Gen 2 (8 Cores) • Termux PRoot • Native C99 NEON    ║")
    print(f"╚══════════════════════════════════════════════════════════════════════╝")
    print(f"• Mode:        {args.mode.upper()}")
    print(f"• Universe:    {args.universe}")
    print(f"• Schedule:    {args.schedule.upper()}")
    print(f"• Top N:       {args.top_n}")
    print(f"• Sizing Mode: {args.sizing_mode}")
    print(f"• Period:      {args.start_date} to {args.end_date}")
    print(f"• Threads:     {args.threads}")
    print(f"• Output Dir:  {out_dir}\n")

    runner = BruteForceCampaignRunner(force_recompile=args.force_recompile)
    cube = runner.ensure_cube(universe_name=args.universe)

    if args.mode == "baseline":
        res = runner.run_baseline(
            start_date=args.start_date,
            end_date=args.end_date,
            schedule=args.schedule,
            universe_name=args.universe,
        )
        json_path = out_dir / "canonical_baseline_results.json"
        with open(json_path, "w") as f:
            json.dump(res, f, indent=2)

        print("\n============================================================")
        print(" CANONICAL BASELINE SIMULATION REPORT")
        print("============================================================")
        for k, v in res.items():
            print(f"  {k:<22}: {v}")
        print(f"\nSaved baseline summary to: {json_path}")
        return res

    elif args.mode == "tier1":
        grid = generate_tier1_baseline_matrix(cube)
        df = runner.run_sweep(grid, num_threads=args.threads)
        csv_path = out_dir / "tier1_baseline_matrix.csv"
        df.to_csv(csv_path, index=False)
        print(f"\nSaved {len(df):,} configurations to: {csv_path}")
        return df

    elif args.mode == "tier2":
        grid = generate_tier2_ablation_grid(cube)
        df = runner.run_sweep(grid, num_threads=args.threads)
        csv_path = out_dir / "tier2_ablation_matrix.csv"
        df.to_csv(csv_path, index=False)
        print(f"\nSaved {len(df):,} configurations to: {csv_path}")
        return df

    elif args.mode == "comprehensive":
        grid = generate_tier3_hyperparameter_grid(cube, sample_size=10000)
        df = runner.run_sweep(grid, num_threads=args.threads)
        csv_path = out_dir / "brute_force_comprehensive_results.csv"
        df.to_csv(csv_path, index=False)

        top_sharpe = df.sort_values(by="sharpe", ascending=False).head(10)
        summary_path = out_dir / "brute_force_comprehensive_top10.json"
        top_sharpe.to_json(summary_path, orient="records", indent=2)

        print(f"\nSaved {len(df):,} configurations to: {csv_path}")
        print(f"Saved top 10 configurations to: {summary_path}")
        cols = ["param_id", "lookback", "ema_trend", "retrace_threshold", "top_n", "max_per_sector", "cagr", "sharpe", "max_drawdown", "win_rate"]
        print(top_sharpe[cols].head(5).to_string(index=False))
        return df


if __name__ == "__main__":
    main()
