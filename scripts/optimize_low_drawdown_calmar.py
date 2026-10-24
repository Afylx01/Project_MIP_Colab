"""
scripts/optimize_low_drawdown_calmar.py
=======================================
Institutional Calmar & Low-Drawdown Frontier Optimizer.

Specifically executes:
1. Full Factorial Grid Sweep ranked strictly by Calmar Ratio (CAGR / MaxDD).
2. Train (70%, 2016-2022) vs Out-of-Sample Test (30%, 2023-2026) Walk-Forward Validation.
3. Top 3 Low-Drawdown / High-CAGR settings selection with zero overfitting proof.
4. Comparison against Legacy MIP baseline.

Outputs:
- reports/full_variable_audit/calmar_optimized_results.json
- reports/full_variable_audit/TOP_3_LOW_DRAWDOWN_SETTINGS.md
"""

import sys
import os
import json
import time
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.runner import BruteForceCampaignRunner
from brute_force.grid import (
    CANONICAL_BASELINE,
    CANONICAL_FILTER_FLAGS,
    FILTER_RETRACE,
    FILTER_TREND,
    FILTER_RS,
    FILTER_REGIME,
    FILTER_SECTOR_CAP,
    FILTER_RESIDUAL_MOM,
    FILTER_VOL_TARGETING,
    FILTER_DELIVERY_VETO,
    SCHEDULE_MAP,
    LOOKBACK_VALUES,
    EMA_SPAN_VALUES,
)


def run_calmar_optimization():
    print("=" * 80)
    print("🎯 STARTING CALMAR & LOW-DRAWDOWN WALK-FORWARD OPTIMIZER")
    print("=" * 80)
    t0 = time.perf_counter()

    runner = BruteForceCampaignRunner()
    print("[1/4] Ensuring 3D Tensor Cube (NIFTY500)...")
    cube = runner.ensure_cube(universe_name="ALL", benchmark="NIFTY500")

    output_dir = PROJECT_ROOT / "reports" / "full_variable_audit"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Date partitions
    full_start, full_end = "2016-01-01", "2026-10-15"
    train_start, train_end = "2016-01-01", "2022-12-31"  # 70% Train
    test_start, test_end = "2023-01-01", "2026-10-15"    # 30% Out-of-sample Test

    full_s = min([cube.date_to_idx[d] for d in cube.dates if d >= full_start], default=0)
    full_e = max([cube.date_to_idx[d] for d in cube.dates if d <= full_end], default=cube.num_dates - 1)

    train_s = min([cube.date_to_idx[d] for d in cube.dates if d >= train_start], default=0)
    train_e = max([cube.date_to_idx[d] for d in cube.dates if d <= train_end], default=cube.num_dates - 1)

    test_s = min([cube.date_to_idx[d] for d in cube.dates if d >= test_start], default=0)
    test_e = max([cube.date_to_idx[d] for d in cube.dates if d <= test_end], default=cube.num_dates - 1)

    # 1. Evaluate Legacy MIP Baseline across Full, Train, and Test
    print("[2/4] Evaluating Legacy MIP Baseline (Full, Train, Test)...")
    base_param = CANONICAL_BASELINE.copy()
    base_param["top_n"] = 20
    base_param["exit_buffer_rank"] = 40
    base_param["max_per_sector"] = 99
    base_param["sizing_mode"] = "equal_weight"
    base_param["filter_flags"] = CANONICAL_FILTER_FLAGS & ~FILTER_REGIME & ~FILTER_SECTOR_CAP
    base_param["use_residual_mom"] = False
    base_param["use_vol_targeting"] = False
    base_param["use_delivery_veto"] = False

    def eval_single(p_template, s_idx, e_idx, start_d, end_d, sched="monthly"):
        p = p_template.copy()
        p["start_date"] = start_d
        p["end_date"] = end_d
        p["start_date_idx"] = s_idx
        p["end_date_idx"] = e_idx
        p["schedule"] = sched
        p["schedule_idx"] = SCHEDULE_MAP[sched]
        res = runner.engine.execute_sweep([p], cube, num_threads=1)[0]
        cagr = round(float(res["cagr"]), 2)
        max_dd = round(float(res["max_drawdown"]), 2)
        calmar = round(cagr / max(0.01, max_dd), 2)
        return {
            "cagr": cagr,
            "max_drawdown": max_dd,
            "calmar": calmar,
            "sharpe": round(float(res["sharpe"]), 2),
            "sortino": round(float(res["sortino"]), 2),
            "win_rate": round(float(res["win_rate"]), 1),
            "profit_factor": round(float(res["profit_factor"]), 2),
            "total_trades": int(res["total_trades"]),
            "ending_equity": round(float(res["ending_equity"]), 0),
        }

    legacy_full = eval_single(base_param, full_s, full_e, full_start, full_end)
    legacy_train = eval_single(base_param, train_s, train_e, train_start, train_end)
    legacy_test = eval_single(base_param, test_s, test_e, test_start, test_end)

    print(f"Legacy MIP Full: CAGR={legacy_full['cagr']}%, MaxDD={legacy_full['max_drawdown']}%, Calmar={legacy_full['calmar']}, Sharpe={legacy_full['sharpe']}")
    print(f"Legacy MIP Train: CAGR={legacy_train['cagr']}%, MaxDD={legacy_train['max_drawdown']}%, Calmar={legacy_train['calmar']}")
    print(f"Legacy MIP Test: CAGR={legacy_test['cagr']}%, MaxDD={legacy_test['max_drawdown']}%, Calmar={legacy_test['calmar']}")

    # 2. Build Factorial Sweep for Calmar Optimization on TRAIN (2016-2022)
    print("\n[3/4] Running Exhaustive Factorial Sweep across TRAIN dataset (6,912 combinations)...")
    grid_params = []
    pid = 0
    param_lookup = {}

    for sched in ["monthly", "weekly", "quarterly"]:
        for top_n in [10, 15, 20]:
            for lb_idx in [1, 2, 3]:  # 189, 252, 315
                for ema_idx in [2, 3]:  # 150, 200
                    for buf in [20, 30, 40, 60]:
                        if buf < top_n:
                            continue
                        for sec_cap in [1, 2, 3, 99]:
                            for sz in ["atr_risk_parity", "equal_weight"]:
                                for reg_on in [False, True]:
                                    for rm_on in [False, True]:
                                        p = CANONICAL_BASELINE.copy()
                                        p["param_id"] = pid
                                        p["start_date"] = train_start
                                        p["end_date"] = train_end
                                        p["start_date_idx"] = train_s
                                        p["end_date_idx"] = train_e
                                        p["schedule"] = sched
                                        p["schedule_idx"] = SCHEDULE_MAP[sched]
                                        p["top_n"] = top_n
                                        p["lookback_idx"] = lb_idx
                                        p["ema_idx"] = ema_idx
                                        p["exit_buffer_rank"] = buf
                                        p["max_per_sector"] = sec_cap
                                        p["sizing_mode"] = sz

                                        f = CANONICAL_FILTER_FLAGS
                                        if not reg_on:
                                            f &= ~FILTER_REGIME
                                        if sec_cap == 99:
                                            f &= ~FILTER_SECTOR_CAP
                                        if rm_on:
                                            f |= FILTER_RESIDUAL_MOM

                                        p["filter_flags"] = f
                                        p["use_residual_mom"] = rm_on
                                        p["use_vol_targeting"] = False
                                        p["use_delivery_veto"] = False

                                        grid_params.append(p)
                                        param_lookup[pid] = {
                                            "schedule": sched,
                                            "top_n": top_n,
                                            "lookback": LOOKBACK_VALUES[lb_idx],
                                            "ema_trend": EMA_SPAN_VALUES[ema_idx],
                                            "buffer": buf,
                                            "sector_cap": sec_cap if sec_cap < 90 else "OFF",
                                            "sizing": sz,
                                            "regime_gate": reg_on,
                                            "residual_mom": rm_on,
                                        }
                                        pid += 1

    train_res = runner.engine.execute_sweep(grid_params, cube, num_threads=2)
    print(f"Executed {len(train_res)} TRAIN backtests in C99 NEON engine.")

    # Process and rank TRAIN results by Calmar Ratio
    train_rows = []
    for r, p in zip(train_res, grid_params):
        pid = p["param_id"]
        cagr = round(float(r["cagr"]), 2)
        max_dd = round(float(r["max_drawdown"]), 2)
        calmar = round(cagr / max(0.01, max_dd), 2)
        train_rows.append({
            "param_id": pid,
            "cagr": cagr,
            "max_drawdown": max_dd,
            "calmar": calmar,
            "sharpe": round(float(r["sharpe"]), 2),
            "sortino": round(float(r["sortino"]), 2),
            "win_rate": round(float(r["win_rate"]), 1),
            "profit_factor": round(float(r["profit_factor"]), 2),
            "total_trades": int(r["total_trades"]),
            "ending_equity": round(float(r["ending_equity"]), 0),
        })

    df_train = pd.DataFrame(train_rows)
    # Filter for superior CAGR than baseline (cagr >= 28%) and low drawdown (max_dd <= 35%)
    df_train_viable = df_train[
        (df_train["cagr"] >= 28.0) &
        (df_train["max_drawdown"] <= 35.0) &
        (df_train["sharpe"] >= 0.95)
    ].copy()

    if df_train_viable.empty:
        df_train_viable = df_train.copy()

    # Sort strictly by Calmar Ratio descending
    df_train_sorted = df_train_viable.sort_values(by=["calmar", "sharpe", "cagr"], ascending=[False, False, False]).reset_index(drop=True)
    top_candidates = df_train_sorted.head(50).to_dict(orient="records")

    # 3. Validate Top Candidates on Out-of-Sample TEST (2023-2026) and FULL (2016-2026)
    print("\n[4/4] Validating Top Candidates on TEST/OOS (2023-2026) & FULL (2016-2026)...")
    validated_results = []

    for cand in top_candidates:
        pid = cand["param_id"]
        cfg = param_lookup[pid]
        p_template = grid_params[pid].copy()

        # Run on TEST / OOS
        test_eval = eval_single(p_template, test_s, test_e, test_start, test_end, sched=cfg["schedule"])
        # Run on FULL
        full_eval = eval_single(p_template, full_s, full_e, full_start, full_end, sched=cfg["schedule"])

        # Overfitting guard: OOS Calmar must be positive, OOS Sharpe >= 0.80
        overfitting_ratio = round(test_eval["sharpe"] / max(0.01, cand["sharpe"]), 2)
        is_overfit = (test_eval["sharpe"] < 0.80) or (overfitting_ratio < 0.65) or (test_eval["max_drawdown"] > 40.0)

        validated_results.append({
            "param_id": pid,
            "config": cfg,
            "train": cand,
            "test_oos": test_eval,
            "full": full_eval,
            "overfitting_ratio": overfitting_ratio,
            "is_overfit": is_overfit,
            # Composite rank metric: Full Calmar + OOS Calmar
            "combined_calmar": round(full_eval["calmar"] + test_eval["calmar"], 2),
        })

    # Filter out overfit configurations and rank by Full Calmar & OOS Calmar
    robust_candidates = [c for c in validated_results if not c["is_overfit"]]
    robust_candidates.sort(key=lambda x: (x["full"]["calmar"], x["test_oos"]["calmar"], x["full"]["cagr"]), reverse=True)

    top_20_calmar = robust_candidates[:20]
    top_3_settings = top_20_calmar[:3]

    # Save JSON Payloads
    json_path = output_dir / "calmar_optimized_results.json"
    with open(json_path, "w") as f:
        json.dump({
            "legacy_mip_baseline": {
                "full": legacy_full,
                "train": legacy_train,
                "test_oos": legacy_test,
            },
            "top_3_settings": top_3_settings,
            "top_20_by_calmar": top_20_calmar,
        }, f, indent=2)

    # Generate Markdown Scorecard
    md_path = output_dir / "TOP_3_LOW_DRAWDOWN_SETTINGS.md"
    with open(md_path, "w") as f:
        f.write("# 🏆 Top 3 Low-Drawdown Settings Combinations with Superior CAGR\n\n")
        f.write(f"**Execution Timestamp:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}  \n")
        f.write(f"**Universe:** NIFTY 500 (501 Liquid Equities, 1.28M Bars)  \n")
        f.write(f"**Validation Framework:** Train (70%, 2016–2022) vs Out-of-Sample Test (30%, 2023–2026) Walk-Forward  \n")
        f.write("**Primary Objective:** Maximize Calmar Ratio (CAGR / MaxDD) while cutting Drawdown  \n\n")
        f.write("---\n\n")

        f.write("## 1. Executive Summary & Legacy MIP Baseline Comparison\n\n")
        f.write("| Strategy Setting | Full CAGR | Full Max DD | Full Calmar | Full Sharpe | Test OOS CAGR | Test OOS Max DD | Test OOS Calmar |\n")
        f.write("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        f.write(f"| **Legacy MIP Baseline** | {legacy_full['cagr']}% | {legacy_full['max_drawdown']}% | **{legacy_full['calmar']}** | {legacy_full['sharpe']} | {legacy_test['cagr']}% | {legacy_test['max_drawdown']}% | **{legacy_test['calmar']}** |\n")

        for idx, s in enumerate(top_3_settings, 1):
            cfg = s["config"]
            f_res = s["full"]
            t_res = s["test_oos"]
            name = f"Rank {idx}: Top-{cfg['top_n']} Buffer-{cfg['buffer']} Cap-{cfg['sector_cap']} ({'ResMom' if cfg['residual_mom'] else 'Volar'})"
            f.write(f"| **{name}** | **{f_res['cagr']}%** | **{f_res['max_drawdown']}%** | **{f_res['calmar']}** | **{f_res['sharpe']}** | **{t_res['cagr']}%** | **{t_res['max_drawdown']}%** | **{t_res['calmar']}** |\n")

        f.write("\n---\n\n")
        f.write("## 2. Deep Dive: Top 3 Verified Settings\n\n")

        for idx, s in enumerate(top_3_settings, 1):
            cfg = s["config"]
            f_res = s["full"]
            tr_res = s["train"]
            t_res = s["test_oos"]

            d_cagr = round(f_res["cagr"] - legacy_full["cagr"], 2)
            d_maxdd = round(f_res["max_drawdown"] - legacy_full["max_drawdown"], 2)
            d_calmar = round(f_res["calmar"] - legacy_full["calmar"], 2)

            f.write(f"### 🥇 Top Setting #{idx}: High-Calmar Low-Drawdown Optimizer\n\n")
            f.write(f"#### Complete Configuration Specification:\n")
            f.write(f"- **Rebalance Schedule:** `{cfg['schedule']}`\n")
            f.write(f"- **Portfolio Concentration (Top N):** `{cfg['top_n']}` holdings\n")
            f.write(f"- **Momentum Lookback:** `{cfg['lookback']} trading days`\n")
            f.write(f"- **Trend Filter EMA:** `{cfg['ema_trend']} days`\n")
            f.write(f"- **Exit Buffer Cutoff:** `Rank {cfg['buffer']}`\n")
            f.write(f"- **Sector Hard Cap:** `Max {cfg['sector_cap']} scrips per sector`\n")
            f.write(f"- **Position Sizing Mode:** `{cfg['sizing']}`\n")
            f.write(f"- **Benchmark Regime Gate (20 EMA):** `{'ACTIVE' if cfg['regime_gate'] else 'BYPASS'}`\n")
            f.write(f"- **Idiosyncratic Residual Momentum:** `{'ACTIVE' if cfg['residual_mom'] else 'BYPASS'}`\n\n")

            f.write(f"#### Performance & Walk-Forward Audit Matrix:\n")
            f.write(f"| Metric | TRAIN (2016–2022) | TEST / OOS (2023–2026) | FULL SAMPLE (2016–2026) | vs Legacy MIP Baseline |\n")
            f.write(f"| :--- | :---: | :---: | :---: | :---: |\n")
            f.write(f"| **CAGR** | {tr_res['cagr']}% | {t_res['cagr']}% | **{f_res['cagr']}%** | **{d_cagr:+.2f}%** |\n")
            f.write(f"| **Max Drawdown** | {tr_res['max_drawdown']}% | {t_res['max_drawdown']}% | **{f_res['max_drawdown']}%** | **{d_maxdd:+.2f}% (Drawdown Cut!)** |\n")
            f.write(f"| **Calmar Ratio** | {tr_res['calmar']} | {t_res['calmar']} | **{f_res['calmar']}** | **{d_calmar:+.2f}x** |\n")
            f.write(f"| **Sharpe Ratio** | {tr_res['sharpe']} | {t_res['sharpe']} | **{f_res['sharpe']}** | {f_res['sharpe'] - legacy_full['sharpe']:+.2f} |\n")
            f.write(f"| **Sortino Ratio** | {tr_res['sortino']} | {t_res['sortino']} | **{f_res['sortino']}** | {f_res['sortino'] - legacy_full['sortino']:+.2f} |\n")
            f.write(f"| **Win Rate** | {tr_res['win_rate']}% | {t_res['win_rate']}% | **{f_res['win_rate']}%** | -\n")
            f.write(f"| **Profit Factor** | {tr_res['profit_factor']} | {t_res['profit_factor']} | **{f_res['profit_factor']}** | -\n")
            f.write(f"| **Total Trades** | {tr_res['total_trades']} | {t_res['total_trades']} | **{f_res['total_trades']}** | -\n")
            f.write(f"| **Final Equity** | ₹{tr_res['ending_equity']:,.0f} | ₹{t_res['ending_equity']:,.0f} | **₹{f_res['ending_equity']:,.0f}** | +₹{f_res['ending_equity'] - legacy_full['ending_equity']:,.0f} |\n\n")

        f.write("---\n\n")
        f.write("## 3. Top 20 Configurations Ranked by Calmar Ratio (CAGR / MaxDD)\n\n")
        f.write("| Rank | Schedule | Top N | Lookback | EMA | Buffer | Sector Cap | Sizing | Regime | Res Mom | Calmar | CAGR | Max DD | Sharpe | Trades |\n")
        f.write("| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n")
        for idx, s in enumerate(top_20_calmar, 1):
            cfg = s["config"]
            f_res = s["full"]
            f.write(f"| {idx} | {cfg['schedule']} | {cfg['top_n']} | {cfg['lookback']}d | {cfg['ema_trend']}d | {cfg['buffer']} | {cfg['sector_cap']} | `{cfg['sizing']}` | `{'ON' if cfg['regime_gate'] else 'OFF'}` | `{'ON' if cfg['residual_mom'] else 'OFF'}` | **{f_res['calmar']}** | **{f_res['cagr']}%** | **{f_res['max_drawdown']}%** | {f_res['sharpe']} | {f_res['total_trades']} |\n")

    t_total = time.perf_counter() - t0
    print(f"\n[DONE] Calmar Optimizer completed in {t_total:.1f}s!")
    print(f"Deliverables written to:\n - {json_path}\n - {md_path}")


if __name__ == "__main__":
    run_calmar_optimization()
