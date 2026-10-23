"""
Project MIP Pydroid 3: Sector Rotation Engine
Directive: DIR-PROD-PYDROID3-PORT-01 (Official 20-Industry AMFI Institutional Edition)

Computes comprehensive Sector Rotation analytics across the official 20+ AMFI/NSE industries:
  1. Equal-weighted 1M (21d), 3M (63d), 6M (126d), 1Y (252d) industry returns.
  2. Relative Strength Alpha vs Benchmark (Alpha_1M, Alpha_3M, Alpha_6M).
  3. Industry Internal Breadth (% > 200 EMA, % > 50 EMA, Delta, Elite Breadth %, New 52W Highs).
  4. Industry RRG Quadrant (Mean RS-Ratio and RS-Momentum), Rotation State, Action Matrix.
  5. Top 20 Momentum Candidate Density & Top 3 Industry Leaders.
  6. Composite Sector Rank Score:
       Score = 0.5 * Alpha_1M + 0.5 * Alpha_3M + 0.2 * (Sector_Breadth_200 - 50.0)
"""

import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd
import numpy as np

from .data_engine import (
    get_base_dir,
    get_latest_date,
    load_bars,
    load_symbol_sector_map,
)
from .rrg import classify_quadrant


class SectorRotationEngine:
    """Quantitative Sector & Industry Rotation Engine for Pydroid 3."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or get_base_dir()
        self.sector_map = load_symbol_sector_map()
        self.benchmark_csv = self.base_dir / "data" / "benchmark_nifty500.csv"

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [SectorEngine] {msg}")

    def load_benchmark(self) -> pd.DataFrame:
        if not self.benchmark_csv.exists():
            return pd.DataFrame(columns=["date", "close"])
        df = pd.read_csv(self.benchmark_csv)
        df["date"] = df["date"].astype(str)
        return df

    def get_benchmark_returns(self, as_of_date: str) -> Dict[str, float]:
        """Calculates benchmark 21-day, 63-day, 126-day, and 252-day returns."""
        b_df = self.load_benchmark()
        if b_df.empty:
            return {"bm_ret_1m": 0.0, "bm_ret_3m": 0.0, "bm_ret_6m": 0.0, "bm_ret_1y": 0.0}

        row = b_df[b_df["date"] == as_of_date]
        if row.empty:
            prior = b_df[b_df["date"] <= as_of_date]
            if prior.empty:
                return {"bm_ret_1m": 0.0, "bm_ret_3m": 0.0, "bm_ret_6m": 0.0, "bm_ret_1y": 0.0}
            idx = prior.index[-1]
        else:
            idx = row.index[0]

        curr_close = b_df.loc[idx, "close"]
        idx_1m = max(0, idx - 21)
        idx_3m = max(0, idx - 63)
        idx_6m = max(0, idx - 126)
        idx_1y = max(0, idx - 252)

        ret_1m = (curr_close / b_df.loc[idx_1m, "close"] - 1.0) * 100.0
        ret_3m = (curr_close / b_df.loc[idx_3m, "close"] - 1.0) * 100.0
        ret_6m = (curr_close / b_df.loc[idx_6m, "close"] - 1.0) * 100.0
        ret_1y = (curr_close / b_df.loc[idx_1y, "close"] - 1.0) * 100.0

        return {
            "bm_ret_1m": round(ret_1m, 2),
            "bm_ret_3m": round(ret_3m, 2),
            "bm_ret_6m": round(ret_6m, 2),
            "bm_ret_1y": round(ret_1y, 2),
        }

    def compute_sector_rotation(
        self,
        as_of_date: Optional[str] = None,
        snapshot_df: Optional[pd.DataFrame] = None,
        top_20_symbols: Optional[List[str]] = None,
    ) -> Dict:
        """
        Computes all sector rotation metrics, returns, alpha, breadth, and ranking
        dynamically across all active AMFI industries.
        """
        target_date = as_of_date or get_latest_date()
        self.log(f"Computing Sector Rotation as of {target_date}...")

        top_20_set = set(top_20_symbols) if top_20_symbols else set()
        bm_returns = self.get_benchmark_returns(target_date)

        # If snapshot_df contains precomputed columns, use it
        req_cols = {"symbol", "close", "ema_200", "high_252"}
        if snapshot_df is not None and req_cols.issubset(set(snapshot_df.columns)):
            snap = snapshot_df.copy()
            if "date" in snap.columns:
                snap = snap[snap["date"] == target_date].copy()
        else:
            # Slices bars for past 400 days
            target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            start_str = (target_dt - datetime.timedelta(days=400)).strftime("%Y-%m-%d")

            bars = load_bars(start_date=start_str, end_date=target_date, include_delisted=False)
            active_today = set(bars[bars["date"] == target_date]["symbol"].unique())
            bars = bars[bars["symbol"].isin(active_today)].copy()
            bars = bars.sort_values(by=["symbol", "date"]).reset_index(drop=True)

            # Returns and EMAs
            bars["close_21d"] = bars.groupby("symbol")["close"].shift(21)
            bars["close_63d"] = bars.groupby("symbol")["close"].shift(63)
            bars["close_126d"] = bars.groupby("symbol")["close"].shift(126)
            bars["close_252d"] = bars.groupby("symbol")["close"].shift(252)

            bars["ret_1m"] = (bars["close"] / bars["close_21d"] - 1.0) * 100.0
            bars["ret_3m"] = (bars["close"] / bars["close_63d"] - 1.0) * 100.0
            bars["ret_6m"] = (bars["close"] / bars["close_126d"] - 1.0) * 100.0
            bars["ret_1y"] = (bars["close"] / bars["close_252d"] - 1.0) * 100.0

            bars["ema_200"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=200, adjust=True, min_periods=min(50, len(s))).mean()
            )
            bars["ema_50"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=50, adjust=True, min_periods=min(20, len(s))).mean()
            )
            bars["high_252"] = bars.groupby("symbol")["high"].transform(
                lambda s: s.rolling(252, min_periods=min(50, len(s))).max()
            )
            snap = bars[bars["date"] == target_date].copy()

        # The scanner passes a snapshot with RRG columns already computed. The
        # standalone flow does not, so compute them here instead of silently
        # defaulting every sector to RS-Ratio=RS-Momentum=100 (which labels all
        # sectors LEADING).
        if "rrg_rs_ratio" not in snap.columns or "rrg_rs_momentum" not in snap.columns:
            b_df = self.load_benchmark()
            if not b_df.empty and "bars" in locals() and not bars.empty:
                bm_map = dict(zip(b_df["date"].astype(str), b_df["close"]))
                bars["benchmark_close"] = bars["date"].map(bm_map)
                from .rrg import compute_rrg_metrics
                bars = compute_rrg_metrics(bars)
                snap = bars[bars["date"] == target_date].copy()
                self.log("Computed RRG metrics for standalone sector rotation.")

        # Attach official AMFI industry taxonomy
        snap["sector"] = snap["symbol"].map(self.sector_map).fillna("SERVICES")

        # Discover all unique industries present in snapshot
        unique_sectors = sorted([s for s in snap["sector"].dropna().unique() if str(s).strip()])

        # Compute Sector Metrics
        sector_results = []
        for sec in unique_sectors:
            sec_df = snap[snap["sector"] == sec]
            n_stocks = len(sec_df)
            if n_stocks == 0:
                continue

            # Return calculations
            if "ret_1m" in sec_df.columns:
                m1 = float(sec_df["ret_1m"].mean())
                ret_1m = m1 if abs(m1) > 0.05 or m1 == 0.0 else m1 * 100.0
            elif "ret_21" in sec_df.columns:
                ret_1m = float((sec_df["ret_21"] * 100.0).mean())
            else:
                ret_1m = 0.0

            if "ret_3m" in sec_df.columns:
                m3 = float(sec_df["ret_3m"].mean())
                ret_3m = m3 if abs(m3) > 0.05 or m3 == 0.0 else m3 * 100.0
            elif "ret_63" in sec_df.columns:
                ret_3m = float((sec_df["ret_63"] * 100.0).mean())
            else:
                ret_3m = 0.0

            if "ret_6m" in sec_df.columns:
                m6 = float(sec_df["ret_6m"].mean())
                ret_6m = m6 if abs(m6) > 0.05 or m6 == 0.0 else m6 * 100.0
            else:
                ret_6m = 0.0

            if "ret_1y" in sec_df.columns:
                my = float(sec_df["ret_1y"].mean())
                ret_1y = my if abs(my) > 5.0 or my == 0.0 else my * 100.0
            elif "ret_252" in sec_df.columns:
                ret_1y = float((sec_df["ret_252"] * 100.0).mean())
            else:
                ret_1y = 0.0

            alpha_1m = ret_1m - bm_returns["bm_ret_1m"]
            alpha_3m = ret_3m - bm_returns["bm_ret_3m"]
            alpha_6m = ret_6m - bm_returns.get("bm_ret_6m", 0.0)

            # Internal Breadth
            above_200 = int((sec_df["close"] > sec_df["ema_200"]).sum()) if "ema_200" in sec_df.columns else 0
            breadth_200_pct = round((above_200 / n_stocks) * 100.0, 1)

            above_50 = int((sec_df["close"] > sec_df["ema_50"]).sum()) if "ema_50" in sec_df.columns else above_200
            breadth_50_pct = round((above_50 / n_stocks) * 100.0, 1)
            delta = round(breadth_50_pct - breadth_200_pct, 1)

            within_20 = int((sec_df["close"] >= 0.80 * sec_df["high_252"]).sum()) if "high_252" in sec_df.columns else 0
            near_high_pct = round((within_20 / n_stocks) * 100.0, 1)

            elite_count = int(((sec_df["close"] > sec_df["ema_200"]) & (sec_df["close"] >= 0.85 * sec_df["high_252"])).sum()) if ("ema_200" in sec_df.columns and "high_252" in sec_df.columns) else 0
            elite_pct = round((elite_count / n_stocks) * 100.0, 1)

            new_52w_highs = int((sec_df["close"] >= 0.99 * sec_df["high_252"]).sum()) if "high_252" in sec_df.columns else 0

            # RRG Dynamics
            avg_rs_ratio = float(sec_df["rrg_rs_ratio"].mean()) if "rrg_rs_ratio" in sec_df.columns else 100.0
            avg_rs_mom = float(sec_df["rrg_rs_momentum"].mean()) if "rrg_rs_momentum" in sec_df.columns else 100.0
            rrg_quad = classify_quadrant(avg_rs_ratio, avg_rs_mom)

            # Top 3 Industry Leaders (by Volar score if available, else by 1M return)
            if "volar_score" in sec_df.columns:
                leader_syms = sec_df.sort_values(by="volar_score", ascending=False)["symbol"].tolist()[:3]
            elif "ret_1m" in sec_df.columns:
                leader_syms = sec_df.sort_values(by="ret_1m", ascending=False)["symbol"].tolist()[:3]
            else:
                leader_syms = sec_df["symbol"].tolist()[:3]
            top_3_leaders = ", ".join(leader_syms)

            # Top 20 Candidates count
            top_20_count = int(sec_df["symbol"].isin(top_20_set).sum())
            top_20_share = round((top_20_count / 20.0) * 100.0, 1) if top_20_symbols else 0.0

            # Rotation State
            if rrg_quad == "LEADING":
                rotation_state = "STRONG UPTREND" if alpha_1m >= 0 else "MATURING LEAD"
            elif rrg_quad == "IMPROVING":
                rotation_state = "EARLY RECOVERY"
            elif rrg_quad == "WEAKENING":
                rotation_state = "WEAKENING DOWNTREND"
            else:
                rotation_state = "LAGGING"

            # Signal Agreement (0-5 score)
            agr = 0
            if alpha_1m > 0: agr += 1
            if alpha_3m > 0: agr += 1
            if breadth_200_pct >= 50.0: agr += 1
            if rrg_quad in ["LEADING", "IMPROVING"]: agr += 1
            if new_52w_highs > 0: agr += 1

            # Action Matrix
            if rrg_quad == "LEADING" and agr >= 4:
                action = "STRONG ACCUMULATE"
            elif rrg_quad in ["LEADING", "IMPROVING"] and agr >= 3:
                action = "ACCUMULATE"
            elif agr == 2:
                action = "NEUTRAL"
            elif rrg_quad == "WEAKENING":
                action = "CAUTION"
            else:
                action = "AVOID"

            # Breadth Score (0-100)
            if "ret_1m" in sec_df.columns:
                rs_pos_pct = round(float((sec_df["ret_1m"] > 0).mean()) * 100.0, 1)
            elif "ret_21" in sec_df.columns:
                rs_pos_pct = round(float((sec_df["ret_21"] > 0).mean()) * 100.0, 1)
            elif "ret_1y" in sec_df.columns:
                rs_pos_pct = round(float((sec_df["ret_1y"] > 0).mean()) * 100.0, 1)
            else:
                rs_pos_pct = 50.0
            breadth_score = round(0.40 * rs_pos_pct + 0.40 * breadth_200_pct + 0.20 * elite_pct, 1)

            # Composite Score for Ranking
            composite_score = round(0.5 * alpha_1m + 0.5 * alpha_3m + 0.2 * (breadth_200_pct - 50.0), 2)

            # Clean display name
            display_name = sec.replace("_", " ").title()

            sector_results.append({
                "sector": sec,
                "name": display_name,
                "stock_count": n_stocks,
                "top_3_leaders": top_3_leaders,
                "ret_1m": round(ret_1m, 2),
                "ret_3m": round(ret_3m, 2),
                "ret_6m": round(ret_6m, 2),
                "ret_1y": round(ret_1y, 2),
                "alpha_1m": round(alpha_1m, 2),
                "alpha_3m": round(alpha_3m, 2),
                "alpha_6m": round(alpha_6m, 2),
                "excess_1m": round(alpha_1m, 2),
                "excess_3m": round(alpha_3m, 2),
                "excess_6m": round(alpha_6m, 2),
                "breadth_200_pct": breadth_200_pct,
                "breadth_50_pct": breadth_50_pct,
                "delta": delta,
                "near_high_pct": near_high_pct,
                "elite_pct": elite_pct,
                "new_52w_highs": new_52w_highs,
                "breadth_score": breadth_score,
                "rrg_rs_ratio": round(avg_rs_ratio, 2),
                "rrg_rs_momentum": round(avg_rs_mom, 2),
                "rrg_quadrant": rrg_quad,
                "rotation_state": rotation_state,
                "signal_agreement": agr,
                "action": action,
                "top_20_count": top_20_count,
                "top_20_share_pct": top_20_share,
                "composite_score": composite_score,
            })

        # Rank by composite score descending
        sector_results.sort(key=lambda x: x["composite_score"], reverse=True)
        for rank, s in enumerate(sector_results, 1):
            s["rank"] = rank

        output = {
            "as_of_date": target_date,
            "benchmark_returns": bm_returns,
            "sectors": sector_results,
            "top_sector": sector_results[0]["sector"] if sector_results else "",
            "bottom_sector": sector_results[-1]["sector"] if sector_results else "",
        }

        # Export to reports/
        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_file = reports_dir / "sector_rotation_live.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)

        return output
