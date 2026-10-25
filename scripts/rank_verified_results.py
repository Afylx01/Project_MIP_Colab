#!/usr/bin/env python3
"""Rank the verified campaign: bootstrap CIs, Deflated Sharpe, top-5 selection.

Inputs (produced by run_verified_campaign.py plus the Python cross-engine runs):
  reports/verified/full_grid.csv
  reports/verified/random_windows.csv
  reports/verified/window_robustness.csv
  reports/verified/python_validation.json

Outputs:
  reports/verified/bootstrap.json
  reports/verified/statistics.json
  reports/verified/top5_final.csv

The canonical configuration is scored separately and is never part of the
top-5 (the objective forbids changing the strategy; the five are optimisation
candidates for future forward testing).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
V = ROOT / "reports" / "verified"
SEED = 20261025
BOOT = 5000


def bootstrap(rows: list[dict]) -> list[dict]:
    rng = np.random.default_rng(SEED)
    out = []
    for x in rows:
        r = np.asarray(x["monthly_returns"], dtype=float)
        n = len(r)

        def stats(sample):
            eq = np.cumprod(1 + sample)
            cagr = (eq[-1] ** (12 / len(sample)) - 1) * 100
            sh = (sample.mean() * 12 - 0.065) / (sample.std(ddof=1) * np.sqrt(12))
            return cagr, sh

        boots = np.array([stats(rng.choice(r, size=n, replace=True)) for _ in range(BOOT)])
        out.append({
            "name": x["name"], "months": n, "cagr": x["cagr_pct"], "sharpe": x["sharpe_ratio"],
            "cagr_ci": [round(float(v), 2) for v in np.percentile(boots[:, 0], [5, 50, 95])],
            "sharpe_ci": [round(float(v), 2) for v in np.percentile(boots[:, 1], [5, 50, 95])],
            "p_sharpe_pos": round(float((boots[:, 1] > 0).mean()), 3),
        })
    return out


def deflated_sharpe(grid: pd.DataFrame, sr_ann: float, months: int = 104) -> dict:
    from math import e, sqrt
    from statistics import NormalDist

    sr_m = sr_ann / sqrt(12)
    var = float(np.var(grid["sharpe"].dropna().values / sqrt(12), ddof=1))
    n = len(grid)
    phi = NormalDist().inv_cdf
    gamma = 0.5772156649
    sr0 = sqrt(var) * ((1 - gamma) * phi(1 - 1.0 / n) + gamma * phi(1 - 1.0 / (n * e)))
    return {"trials": n, "sr_annual": sr_ann, "sr0_annual": round(float(sr0) * sqrt(12), 3),
            "dsr": round(float(NormalDist().cdf((sr_m - sr0) * sqrt(months - 1))), 3)}


def main() -> int:
    grid = pd.read_csv(V / "full_grid.csv")
    rw = pd.read_csv(V / "random_windows.csv")
    key = ["top_n", "lookback", "ema_trend", "retrace_threshold", "max_per_sector"]
    for k in key:
        rw[k] = rw[k].astype(float)
    rw["cfg"] = rw[key].astype(str).agg("|".join, axis=1)
    ranks = rw.pivot_table(index=["start_date", "end_date"], columns="cfg", values="cagr").rank(
        axis=1, ascending=False
    )
    wr = pd.read_csv(V / "window_robustness.csv")
    py = pd.DataFrame(json.loads((V / "python_validation.json").read_text()))
    py["cfg"] = py["config"].map(
        lambda c: "|".join(str(float(c[k])) for k in
                           ["top_n", "lookback_bars", "ema_trend_span", "retrace_threshold", "max_per_sector"])
    )
    bs = {b["name"]: b for b in bootstrap(py.to_dict("records"))}
    (V / "bootstrap.json").write_text(json.dumps(list(bs.values()), indent=2))

    rows = []
    for _, p in py.iterrows():
        c = p["cfg"]
        in_rank = c in ranks.columns
        num = [float(v) for v in c.split("|")]
        w = wr[(wr.top_n == num[0]) & (wr.lookback == num[1]) & (wr.ema_trend == num[2])
               & (wr.retrace_threshold == num[3]) & (wr.max_per_sector == num[4])]
        b = bs.get(p["name"], {})
        rows.append({
            "name": p["name"], "top_n": num[0], "lookback": num[1], "ema": num[2],
            "retrace": num[3], "sector": num[4],
            "py_cagr": p["cagr_pct"], "py_sharpe": p["sharpe_ratio"], "py_dd": p["max_drawdown_pct"],
            "trades": p["total_trades"],
            "med_rank": float(ranks[c].median()) if in_rank else np.nan,
            "wins": int((ranks[c] == 1).sum()) if in_rank else 0,
            "w_med_cagr": float(w["cagr"].median()) if len(w) else np.nan,
            "w_worst": float(w["cagr"].min()) if len(w) else np.nan,
            "w_med_excess": float(w["excess"].median()) if len(w) else np.nan,
            "sh_lo": b.get("sharpe_ci", [np.nan] * 3)[0],
            "sh_hi": b.get("sharpe_ci", [np.nan] * 3)[2],
        })
    df = pd.DataFrame(rows)
    df["rank_score"] = (11 - df["med_rank"].fillna(6)) / 10
    df["score"] = (0.35 * df["py_sharpe"].fillna(0) + 0.25 * df["rank_score"]
                   + 0.20 * (df["w_med_excess"].fillna(df["w_med_cagr"]).fillna(0) / 20)
                   + 0.10 * (df["w_worst"].fillna(-10) / 10)
                   + 0.10 * (1 - df["py_dd"].abs().fillna(40) / 40))
    df = df.sort_values("score", ascending=False)
    df.to_csv(V / "top5_final.csv", index=False)

    stats = {
        "sharpe_mean": round(float(grid["sharpe"].mean()), 3),
        "sharpe_std": round(float(grid["sharpe"].std()), 3),
        "sharpe_min": round(float(grid["sharpe"].min()), 3),
        "sharpe_max": round(float(grid["sharpe"].max()), 3),
        "top": deflated_sharpe(grid, float(grid["sharpe"].max())),
        "canonical": deflated_sharpe(grid, 0.62),
    }
    (V / "statistics.json").write_text(json.dumps(stats, indent=2))
    print(df.round(2).to_string(index=False))
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
