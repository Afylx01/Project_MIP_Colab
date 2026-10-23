"""Regenerate the canonical production backtest on NIFTY500.

Canonical contract:
  engine   : Python LightweightBacktester (production contract)
  universe : NIFTY500 current constituents (survivorship flagged)
  config   : top20 / buffer40 / cap2 / ATR risk parity / regime on
  period   : 2016-01-01 .. 2026-08-31
  costs    : 15 bps friction + 5 bps slippage

Writes reports/backtest_results.json, reports/trade_log.csv,
reports/analysis_evidence/04_backtest.json and 05_ledger_audit.json.
"""
import sys, json, shutil
from pathlib import Path
ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from core.backtest import LightweightBacktester
from reports.analysis_evidence.audit_ledger import audit

OUT = ROOT / "reports" / "analysis_evidence"
REPORTS = ROOT / "reports"

# Preserve the legacy ALL-universe run as a labelled reference before the
# canonical artifact is replaced.
legacy = OUT / "04_backtest.json"
if legacy.exists() and not (OUT / "04b_backtest_all.json").exists():
    shutil.copyfile(legacy, OUT / "04b_backtest_all.json")

bt = LightweightBacktester(base_dir=ROOT, output_dir=REPORTS)
res = bt.run(
    start_date="2016-01-01", end_date="2026-08-31",
    top_n=20, exit_buffer=40, use_regime_filter=True,
    max_per_sector=2, sizing_mode="atr_risk_parity",
    risk_per_trade_pct=1.0, universe_mode="NIFTY500",
)
(OUT / "04_backtest.json").write_text(json.dumps(res, indent=2, default=str))
audit(REPORTS / "trade_log.csv", OUT / "04_backtest.json", OUT / "05_ledger_audit.json")
print(json.dumps({k: res[k] for k in (
    "cagr_pct", "sharpe_ratio", "max_drawdown_pct", "daily_max_drawdown_pct",
    "total_trades", "universe_mode", "universe_size", "survivorship_bias_risk",
    "final_equity", "deferred_fills", "calendar_filtered_dates")}, indent=2))
