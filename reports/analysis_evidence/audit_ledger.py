"""Independent ledger audit for a LightweightBacktester trade log."""
import json, math, sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

STT = 0.001
EXCHANGE = 0.0000345
BROKERAGE = 0.0003
GST = 0.18
STAMP = 0.00015
SLIPPAGE = 0.0005
FRIC_RATE = STT + EXCHANGE + BROKERAGE + GST * (BROKERAGE + EXCHANGE) + STAMP
RF = 0.065


def audit(trade_log_path, results_path, out_path):
    df = pd.read_csv(trade_log_path)
    res = json.loads(Path(results_path).read_text())
    reasons = df["exit_reason"].value_counts().to_dict()

    cost_recalc = df["shares"] * df["entry_px"] * (1 + FRIC_RATE + SLIPPAGE)
    proc_recalc = df["shares"] * df["exit_px"] * (1 - FRIC_RATE - SLIPPAGE)
    pnl_err = (df["net_proceeds"] - df["cost_basis"] - df["net_pnl"]).abs()
    ret_err = (df["net_pnl"] / df["cost_basis"] * 100 - df["return_pct"]).abs()
    fric_err = pd.concat([(cost_recalc - df["cost_basis"]).abs(),
                          (proc_recalc - df["net_proceeds"]).abs()])

    monthly = np.asarray(res.get("monthly_returns", []), dtype=float)
    nav = np.concatenate([[1.0], np.cumprod(1 + monthly)])
    peak = np.maximum.accumulate(nav)
    mdd = ((nav - peak) / peak).min()
    comp = float(nav[-1])
    equity_ratio = float(res["final_equity"] / res["initial_capital"])
    years = float(res["years"])
    cagr = (comp ** (1 / years) - 1) * 100
    vol = monthly.std(ddof=1) * math.sqrt(12)
    sharpe = (monthly.mean() * 12 - RF) / vol if vol > 0 else 0.0

    try:
        from core.data_engine import load_trading_calendar
        calendar = set(str(d) for d in load_trading_calendar())
    except Exception:
        calendar = set()
    entries = df["entry_date"].astype(str)
    on_calendar = int(entries.isin(calendar).sum()) if calendar else None

    # Zero-volume / missing entry bars against the raw price store.
    zero_vol = missing_bar = None
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{ROOT/'data'/'universe.db'}?mode=ro", uri=True)
        vol = pd.read_sql_query(
            "SELECT symbol, date, volume FROM prices WHERE date >= ? AND date <= ?",
            con, params=[str(entries.min()), str(entries.max())])
        con.close()
        merged = df.merge(vol, left_on=["symbol", "entry_date"],
                          right_on=["symbol", "date"], how="left")
        missing_bar = int(merged["volume"].isna().sum())
        zero_vol = int((merged["volume"].fillna(0) <= 0).sum())
    except Exception as e:
        missing_bar = f"INCOMPLETE: {e}"

    dates = pd.to_datetime(df["entry_date"])
    exits = pd.to_datetime(df["exit_date"])
    out = {
        "trades": int(len(df)),
        "shares_all_integer": bool((df["shares"] == df["shares"].astype(int)).all()),
        "shares_all_positive": bool((df["shares"] > 0).all()),
        "prices_positive": bool((df["entry_px"] > 0).all() and (df["exit_px"] > 0).all()),
        "chronology_ok": bool((exits >= dates).all()),
        "dates_le_end": bool((exits <= pd.Timestamp(res["end_date"])).all()),
        "symbols": int(df["symbol"].nunique()),
        "pnl_identity_max_err_inr": round(float(pnl_err.max()), 4),
        "return_pct_max_err": round(float(ret_err.max()), 6),
        "friction_net_proceeds_max_err_inr": round(float(fric_err.max()), 4),
        "friction_net_proceeds_mean_err_inr": round(float(fric_err.mean()), 6),
        "rows_with_friction_mismatch_gt_1inr": int((fric_err > 1.0).sum()),
        "exit_reasons": {str(k): int(v) for k, v in reasons.items()},
        "monthly_returns": int(len(monthly)),
        "compounded_growth": round(comp, 6),
        "equity_ratio": round(equity_ratio, 6),
        "compounding_abs_err": round(abs(comp - equity_ratio), 6),
        "cagr_recalc_pct": round(float(cagr), 4),
        "cagr_reported_pct": res.get("cagr_pct"),
        "cagr_abs_err": round(abs(cagr - float(res.get("cagr_pct", 0))), 4),
        "maxdd_recalc_pct": round(float(mdd * 100), 4),
        "maxdd_reported_pct": res.get("max_drawdown_pct"),
        "maxdd_abs_err": round(abs(mdd * 100 - float(res.get("max_drawdown_pct", 0))), 4),
        "sharpe_recalc": round(float(sharpe), 4),
        "sharpe_reported": res.get("sharpe_ratio"),
        "sharpe_abs_err": round(abs(sharpe - float(res.get("sharpe_ratio", 0))), 4),
        "win_rate_recalc_pct": round(float((df["net_pnl"] > 0).mean() * 100), 2),
        "win_rate_reported_pct": res.get("win_rate_pct"),
        "total_cost_basis_inr": round(float(df["cost_basis"].sum()), 2),
        "total_net_proceeds_inr": round(float(df["net_proceeds"].sum()), 2),
        "total_net_pnl_inr": round(float(df["net_pnl"].sum()), 2),
        "avg_hold_days": round(float((exits - dates).dt.days.mean()), 1),
        "entries_on_trading_days": on_calendar,
        "entries_zero_volume": zero_vol,
        "entries_missing_bar": missing_bar,
        "entries_total": int(len(df)),
        "calendar_sessions": len(calendar) if calendar else None,
    }
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(json.dumps({k: v for k, v in out.items() if k != "exit_reasons"}, indent=2))
    return out


if __name__ == "__main__":
    audit(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
