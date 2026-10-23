"""Regenerate 22_candidate_engine_summaries.json (continuous C-kernel runs).

Every row is a single continuous simulation from start to end. max_drawdown_pct
is the kernel's DAILY intra-period drawdown (not the monthly-sampled drawdown in
21_strategy_validation.json). CAGR is annualized on (end_session-start_session)/252.
"""
import sys, json, time
from pathlib import Path

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from brute_force.runner import BruteForceCampaignRunner

OUT = ROOT / "reports" / "analysis_evidence"

CANDIDATES = {
    "A_balanced": dict(lookback=315, ema_trend=250, top_n=20, exit_buffer_rank=30, max_per_sector=2, sizing_mode="equal_weight"),
    "B_max_sharpe": dict(lookback=315, ema_trend=150, top_n=25, exit_buffer_rank=30, max_per_sector=3, sizing_mode="equal_weight"),
    "C_max_cagr": dict(lookback=315, ema_trend=150, top_n=20, exit_buffer_rank=20, max_per_sector=99, sizing_mode="equal_weight"),
    "D_canonical": dict(lookback=252, ema_trend=200, top_n=20, exit_buffer_rank=40, max_per_sector=2, sizing_mode="atr_risk_parity"),
    "E_max_robust": dict(lookback=252, ema_trend=200, top_n=30, exit_buffer_rank=20, max_per_sector=99, sizing_mode="equal_weight"),
}

runner = BruteForceCampaignRunner(base_dir=ROOT)
cube = runner.ensure_cube(universe_name="NIFTY500", benchmark="NIFTY500")

rows = {}
for name, cfg in CANDIDATES.items():
    res = runner.run_custom_backtest(
        start_date="2016-01-01", end_date="2026-08-31",
        universe_name="NIFTY500", benchmark="NIFTY500", schedule="monthly", **cfg,
    )
    rows[name] = {
        "cagr_pct": res["cagr_pct"],
        "sharpe_ratio": res["sharpe_ratio"],
        "sortino_ratio": res["sortino_ratio"],
        "max_drawdown_pct": res["max_drawdown_pct"],
        "calmar_ratio": res["calmar_ratio"],
        "win_rate_pct": res["win_rate_pct"],
        "profit_factor": res["profit_factor"],
        "ending_equity": res["ending_equity"],
        "total_trades": res["total_trades"],
        "turnover_annual_pct": res["turnover_annual_pct"],
        "sim_latency_ms": res["sim_latency_ms"],
        "lookback": res["lookback"],
        "ema_trend": res["ema_trend"],
        "top_n": res["top_n"],
        "exit_buffer_rank": res["exit_buffer_rank"],
        "max_per_sector": res["max_per_sector"],
        "sizing_mode": res["sizing_mode"],
    }
    print(name, rows[name]["cagr_pct"], rows[name]["max_drawdown_pct"], rows[name]["total_trades"])

(OUT / "22_candidate_engine_summaries.json").write_text(json.dumps(rows, indent=2))
print("saved", OUT / "22_candidate_engine_summaries.json")
