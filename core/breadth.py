"""
Project MIP Pydroid 3: Market Breadth Engine
Directive: DIR-PROD-PYDROID3-PORT-01

Computes comprehensive market breadth indicators across the NIFTY 500 universe:
  1. Trend Participation Breadth (% > 200 EMA, % > 50 EMA, % > 20 EMA)
  2. High Proximity Breadth (% within 20% of 52w High, % within 5% of 52w High)
  3. Net New Highs (52w Highs, 52w Lows, Net Highs-Lows)
  4. Breadth Regime Classification (STRONG EXPANSION, SELECTIVE/NEUTRAL, CONTRACTION/DEFENSIVE)
  5. RRG Universe Distribution (Leading, Improving, Weakening, Lagging)
"""

import json
import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np

from .data_engine import (
    get_base_dir,
    get_latest_date,
    load_bars,
    load_trading_calendar,
)
from .rrg import compute_rrg_metrics


class MarketBreadthEngine:
    """Quantitative Market Breadth & RRG Distribution Engine for Pydroid 3."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or get_base_dir()
        self.benchmark_csv = self.base_dir / "data" / "benchmark_nifty500.csv"

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [BreadthEngine] {msg}")

    def load_benchmark(self) -> pd.DataFrame:
        """Loads continuous benchmark proxy."""
        if not self.benchmark_csv.exists():
            return pd.DataFrame(columns=["date", "close"])
        df = pd.read_csv(self.benchmark_csv)
        df["date"] = df["date"].astype(str)
        return df

    def compute_breadth(
        self,
        as_of_date: Optional[str] = None,
        snapshot_df: Optional[pd.DataFrame] = None,
        lookback_days: int = 550
    ) -> Dict:
        """
        Computes all market breadth metrics and RRG distributions.
        If snapshot_df with indicators is provided, computes directly.
        Otherwise loads bars from SQLite via data_engine.
        """
        target_date = as_of_date or get_latest_date()
        self.log(f"Computing Market Breadth as of {target_date}...")

        req_cols = {"close", "ema_200", "ema_50", "ema_20", "high_252", "low_252"}
        if snapshot_df is not None and req_cols.issubset(set(snapshot_df.columns)):
            snap = snapshot_df[snapshot_df["date"] == target_date].copy() if "date" in snapshot_df.columns else snapshot_df.copy()
        else:
            # Load universe bars and calculate indicators
            target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
            start_str = (target_dt - datetime.timedelta(days=lookback_days)).strftime("%Y-%m-%d")

            self.log(f"Loading bars from SQLite ({start_str} to {target_date})...")
            bars = load_bars(start_date=start_str, end_date=target_date, include_delisted=False)

            active_today = set(bars[bars["date"] == target_date]["symbol"].unique())
            bars = bars[bars["symbol"].isin(active_today)].copy()
            bars = bars.sort_values(by=["symbol", "date"]).reset_index(drop=True)

            self.log("Calculating EMAs (20, 50, 200) and 52-week High/Low...")
            bars["ema_200"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=200, adjust=True, min_periods=min(50, len(s))).mean()
            )
            bars["ema_50"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=50, adjust=True, min_periods=min(20, len(s))).mean()
            )
            bars["ema_20"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=20, adjust=True, min_periods=min(10, len(s))).mean()
            )
            bars["high_252"] = bars.groupby("symbol")["high"].transform(
                lambda s: s.rolling(252, min_periods=min(50, len(s))).max()
            )
            bars["low_252"] = bars.groupby("symbol")["low"].transform(
                lambda s: s.rolling(252, min_periods=min(50, len(s))).min()
            )

            # RRG Indicators
            b_df = self.load_benchmark()
            if not b_df.empty:
                bench_map = dict(zip(b_df["date"], b_df["close"]))
                bars["benchmark_close"] = bars["date"].map(bench_map).fillna(1.0)
            else:
                bars["benchmark_close"] = 1.0

            bars = compute_rrg_metrics(bars)
            snap = bars[bars["date"] == target_date].copy()

        snap["high_252"] = snap["high_252"].fillna(snap["close"])
        snap["low_252"] = snap["low_252"].fillna(snap["close"])
        snap["ema_200"] = snap["ema_200"].fillna(snap["close"])
        snap["ema_50"] = snap["ema_50"].fillna(snap["close"])
        snap["ema_20"] = snap["ema_20"].fillna(snap["close"])

        total_scanned = len(snap)
        if total_scanned == 0:
            raise ValueError(f"No active universe symbols found on {target_date}")

        # 1. Trend Participation Breadth
        above_200 = int((snap["close"] > snap["ema_200"]).sum())
        above_50 = int((snap["close"] > snap["ema_50"]).sum())
        above_20 = int((snap["close"] > snap["ema_20"]).sum())

        pct_above_200 = round((above_200 / total_scanned) * 100.0, 2)
        pct_above_50 = round((above_50 / total_scanned) * 100.0, 2)
        pct_above_20 = round((above_20 / total_scanned) * 100.0, 2)

        # 2. High Proximity Breadth
        within_20pct = int((snap["close"] >= 0.80 * snap["high_252"]).sum())
        within_5pct = int((snap["close"] >= 0.95 * snap["high_252"]).sum())

        pct_within_20 = round((within_20pct / total_scanned) * 100.0, 2)
        pct_within_5 = round((within_5pct / total_scanned) * 100.0, 2)

        # 3. Net New Highs / Lows
        new_highs = int((snap["close"] >= 0.99 * snap["high_252"]).sum())
        new_lows = int((snap["close"] <= 1.01 * snap["low_252"]).sum())
        net_highs_lows = new_highs - new_lows

        # 4. Market Breadth Regime Classification
        if pct_above_200 < 40.0 or (pct_above_200 < 50.0 and net_highs_lows < 0):
            regime_key = "CONTRACTION"
            regime_label = "🔴 CONTRACTION / DEFENSIVE"
            regime_emoji = "🔴"
            regime_desc = "Breadth deterioration; defensive cash posture advised"
        elif pct_above_200 >= 60.0 and pct_above_50 >= 55.0:
            regime_key = "EXPANSION"
            regime_label = "🟢 STRONG EXPANSION"
            regime_emoji = "🟢"
            regime_desc = "Broad-based momentum expansion across market segments"
        else:
            regime_key = "NEUTRAL"
            regime_label = "🟡 SELECTIVE / NEUTRAL"
            regime_emoji = "🟡"
            regime_desc = "Selective leadership; strict risk-adjusted criteria required"

        # 5. RRG Universe Distribution
        rrg_dist = {}
        if "rrg_quadrant" in snap.columns:
            for quad, bias in [
                ("LEADING", "🟢 OUTPERFORM"),
                ("IMPROVING", "🟢 ACCELERATING"),
                ("WEAKENING", "🟡 DECELERATING"),
                ("LAGGING", "🔴 UNDERPERFORM")
            ]:
                cnt = int((snap["rrg_quadrant"] == quad).sum())
                pct = round((cnt / total_scanned) * 100.0, 2)
                rrg_dist[quad] = {
                    "count": cnt,
                    "pct": pct,
                    "bias": bias
                }

        breadth_data = {
            "as_of_date": target_date,
            "universe_size": total_scanned,
            "trend_participation": {
                "pct_above_200_ema": pct_above_200,
                "pct_above_50_ema": pct_above_50,
                "pct_above_20_ema": pct_above_20,
                "count_above_200_ema": above_200,
                "count_above_50_ema": above_50,
                "count_above_20_ema": above_20
            },
            "high_proximity": {
                "pct_within_20pct_52wh": pct_within_20,
                "pct_within_5pct_52wh": pct_within_5,
                "count_within_20pct_52wh": within_20pct,
                "count_within_5pct_52wh": within_5pct
            },
            "net_highs_lows": {
                "new_52w_highs": new_highs,
                "new_52w_lows": new_lows,
                "net_highs_lows": net_highs_lows
            },
            "regime": {
                "key": regime_key,
                "label": regime_label,
                "emoji": regime_emoji,
                "description": regime_desc
            },
            "rrg_distribution": rrg_dist
        }

        # Export to reports/
        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        out_file = reports_dir / "market_breadth_live.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(breadth_data, f, indent=2)

        return breadth_data
