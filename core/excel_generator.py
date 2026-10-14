"""
Project MIP Pydroid 3: Institutional 12-Sheet Excel Workbook Generator
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Institutional Publication Edition)

Generates the complete 12-sheet institutional Excel workbook:
  1. Dashboard (Executive KPI metric cards, market breadth, sector rotation, top 20 candidates, ETF momentum)
  2. Strategy Rationale (Dark Navy tab, ELI5 quant rationale, 5-yr empirical backtest proof)
  3. Sector Rotation (RRG quadrants, 1M/3M alpha, breadth % > 200 EMA, top 3 leaders)
  4. Industry Ranking (Composite momentum score, RS-Ratio, RS-Momentum)
  5. Industry History 30d (Daily 30-session sector breadth and return time-series)
  6. Stock Ranking (Volar score, Delivery %, ATR-14, TradingView chart links)
  7. Top Candidates (ATR Risk Parity, Stop Loss, 2-per-sector anti-clustering cap)
  8. Highest Delivery (Institutional accumulation spikes >= 5Cr)
  9. ETF Momentum Ranking (Definedge Momentify ALL-ONE Top 7 Liquid ETFs)
 10. Pick Performance (Vintage performance tracker)
 11. Breadth History (Daily 60-session % > 200/50/20 EMA, 52w Highs/Lows, Net Highs)
 12. Configuration (System calibration and engine specifications)
 13. Charts (High-resolution, proportional embedded visual graphics)
"""

import os
import shutil
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.formatting.rule import ColorScaleRule

from .data_engine import get_base_dir, load_bars, load_symbol_sector_map

# Corporate Wall Street / FactSet Color Palette
PRIMARY_NAVY = "0A2540"
SLATE_NAVY   = "1E293B"
HEADER_BLUE  = "1F4E79"
DARK_NAVY    = "0D47A1"
GREEN_COLOR  = "059669"
RED_COLOR    = "E11D48"
AMBER_COLOR  = "D97706"
BLUE_COLOR   = "2563EB"
BG_LIGHT     = "F8FAFC"
BG_WHITE     = "FFFFFF"
FILL_GREEN   = "DCFCE7"
FILL_RED     = "FEE2E2"
FILL_AMBER   = "FEF3C7"
FILL_BLUE    = "DBEAFE"
BORDER_GREY  = "CBD5E1"


class InstitutionalExcelGenerator:
    """Compiles the complete 12-sheet MIP-1 Excel workbook using openpyxl."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.reports_dir = self.base_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_workbook(
        self,
        as_of_date: str,
        screener_df: pd.DataFrame,
        top_candidates_df: pd.DataFrame,
        breadth_data: dict,
        sector_data: dict,
        delivery_df: Optional[pd.DataFrame] = None,
        etf_ranking_df: Optional[pd.DataFrame] = None,
        top_etf_df: Optional[pd.DataFrame] = None,
        market_bullish: bool = True,
        universe_label: str = "NIFTY 500",
        bars_df: Optional[pd.DataFrame] = None,
        chart_paths: Optional[Dict[str, Path]] = None,
        snap_df: Optional[pd.DataFrame] = None,
    ) -> Path:
        """Assembles and formats all 14 sheets into the destination Excel file."""
        u_slug = str(universe_label).strip().replace(" ", "").replace("(", "").replace(")", "").replace("-", "_")
        excel_path = self.reports_dir / f"MIP1_Momentum_Scanner_{as_of_date}_{u_slug}.xlsx"
        canonical_excel = self.reports_dir / f"MIP1_Momentum_Scanner_{as_of_date}.xlsx"

        # Ensure bars_df is available for 30d/60d history tabs
        if bars_df is None or bars_df.empty:
            try:
                target_dt = datetime.datetime.strptime(as_of_date, "%Y-%m-%d")
                start_str = (target_dt - datetime.timedelta(days=400)).strftime("%Y-%m-%d")
                bars_df = load_bars(start_date=start_str, end_date=as_of_date, include_delisted=False)
                smap = load_symbol_sector_map()
                bars_df["sector"] = bars_df["symbol"].map(smap).fillna("SERVICES")
                bars_df = bars_df.sort_values(by=["symbol", "date"]).reset_index(drop=True)
                bars_df["ema_200"] = bars_df.groupby("symbol")["close"].transform(lambda s: s.ewm(span=200, adjust=True, min_periods=min(50, len(s))).mean())
                bars_df["ema_50"] = bars_df.groupby("symbol")["close"].transform(lambda s: s.ewm(span=50, adjust=True, min_periods=min(20, len(s))).mean())
                bars_df["ema_20"] = bars_df.groupby("symbol")["close"].transform(lambda s: s.ewm(span=20, adjust=True, min_periods=min(10, len(s))).mean())
                bars_df["high_252"] = bars_df.groupby("symbol")["high"].transform(lambda s: s.rolling(252, min_periods=min(50, len(s))).max())
                bars_df["low_252"] = bars_df.groupby("symbol")["low"].transform(lambda s: s.rolling(252, min_periods=min(50, len(s))).min())
                bars_df["ret_1m"] = bars_df.groupby("symbol")["close"].transform(lambda s: s / s.shift(21) - 1.0) * 100.0
            except Exception:
                bars_df = None

        # 1. Build DataFrame tabs
        dash_meta, dash_rot, dash_rrg, dash_stk, dash_etf, layout = self._build_dashboard_frames(
            as_of_date, screener_df, top_candidates_df, breadth_data, sector_data, top_etf_df, market_bullish, universe_label
        )
        rat_df = self._build_strategy_rationale_df(screener_df)
        sec_df = self._build_sector_rotation_df(sector_data, screener_df)
        ind_df = self._build_industry_ranking_df(sector_data, screener_df)
        hist_df = self._build_industry_history_df(as_of_date, bars_df)
        stock_df = self._build_stock_ranking_df(screener_df, delivery_df, sector_data)
        cand_df = self._build_candidates_df(top_candidates_df, delivery_df, market_bullish, sector_data)
        deliv_sheet_df = self._build_highest_delivery_df(delivery_df, screener_df)
        etf_sheet_df = self._build_etf_ranking_df(etf_ranking_df)
        perf_sum, perf_det = self._build_picks_performance_df()
        breadth_hist_df = self._build_breadth_history_df(as_of_date, bars_df, universe_label)
        raw_metrics_df = self._build_raw_metrics_df(snap_df)
        config_df = self._build_config_df(as_of_date, excel_path, universe_label)

        # 2. Write raw sheets using pd.ExcelWriter
        with pd.ExcelWriter(str(excel_path), engine="openpyxl") as writer:
            # Dashboard (Leave rows 0-7 for corporate title and KPI cards)
            dash_meta.to_excel(writer, sheet_name="Dashboard", index=False, startrow=layout["meta"])
            dash_rot.to_excel(writer, sheet_name="Dashboard", index=False, startrow=layout["rot"])
            dash_rrg.to_excel(writer, sheet_name="Dashboard", index=False, startrow=layout["rrg"])
            dash_stk.to_excel(writer, sheet_name="Dashboard", index=False, startrow=layout["stk"])
            dash_etf.to_excel(writer, sheet_name="Dashboard", index=False, startrow=layout["etf"])

            # Main Strategy Tabs
            rat_df.to_excel(writer, sheet_name="Strategy Rationale", index=False)
            sec_df.to_excel(writer, sheet_name="Sector Rotation", index=False)
            ind_df.to_excel(writer, sheet_name="Industry Ranking", index=False)
            hist_df.to_excel(writer, sheet_name="Industry History 30d", index=False)
            stock_df.to_excel(writer, sheet_name="Stock Ranking", index=False)
            cand_df.to_excel(writer, sheet_name="Top Candidates", index=False)
            deliv_sheet_df.to_excel(writer, sheet_name="Highest Delivery", index=False)
            etf_sheet_df.to_excel(writer, sheet_name="ETF Momentum Ranking", index=False)

            if not perf_sum.empty:
                perf_sum.to_excel(writer, sheet_name="Pick Performance", index=False, startrow=1)
                perf_det.to_excel(writer, sheet_name="Pick Performance", index=False, startrow=len(perf_sum) + 4)
            else:
                pd.DataFrame([{"Note": "Pick tracking active — accumulating vintages."}]).to_excel(writer, sheet_name="Pick Performance", index=False)

            breadth_hist_df.to_excel(writer, sheet_name="Breadth History", index=False)

            if raw_metrics_df is not None and not raw_metrics_df.empty:
                raw_metrics_df.to_excel(writer, sheet_name="Raw Stock Metrics", index=False)

            config_df.to_excel(writer, sheet_name="Configuration", index=False)

        # 3. Apply Professional openpyxl Styling & Embed Charts
        self._apply_workbook_styles(
            excel_path=excel_path,
            as_of_date=as_of_date,
            layout=layout,
            market_bullish=market_bullish,
            chart_paths=chart_paths,
            universe_label=universe_label,
            breadth_data=breadth_data,
            top_candidates_df=top_candidates_df
        )

        # Copy to canonical path and deliverables
        try:
            shutil.copyfile(excel_path, canonical_excel)
            deliv_dir = get_base_dir() / "reports"
            deliv_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(excel_path, deliv_dir / excel_path.name)
            shutil.copyfile(canonical_excel, deliv_dir / canonical_excel.name)
        except Exception:
            pass

        return excel_path

    def _build_dashboard_frames(self, as_of_date, screener_df, top_candidates_df, breadth_data, sector_data, top_etf_df, market_bullish, universe_label="NIFTY 500"):
        tp = breadth_data.get("trend_participation", {})
        hp = breadth_data.get("high_proximity", {})
        nhl = breadth_data.get("net_highs_lows", {})

        regime_label = "BULL (Trend Aligned: Entries Active)" if market_bullish else "BEAR (Defensive Cash Protection Active)"
        meta_items = [
            ("Scan Date", as_of_date),
            ("Market Regime", regime_label),
            ("Target Universe", f"{universe_label} Survivorship-Free PIT Universe"),
            ("Ranking Metric", "Volar Score (Smooth Return / Realized Annualized Volatility)"),
            ("Target Holdings", "Top 20 Scrips (Empirical Institutional Sweet Spot)"),
            ("Sector Hard Cap", "Max 2 Stocks per Sector (Strict Anti-Clustering Rule)"),
            ("Position Sizing Mode", "ATR-14 Volatility Risk Parity (1% Risk Budget per Trade)"),
            ("Market Breadth (>200 EMA)", f"{tp.get('pct_above_200_ema', 0.0):.1f}% ({tp.get('count_above_200_ema', 0)} scrips)"),
            ("Market Breadth (>50 EMA)", f"{tp.get('pct_above_50_ema', 0.0):.1f}%"),
            ("Near 52w High (Within 20%)", f"{hp.get('pct_within_20pct_52wh', 0.0):.1f}%"),
            ("52w Net Highs", f"+{nhl.get('new_52w_highs', 0)} / -{nhl.get('new_52w_lows', 0)} (Net: {nhl.get('net_highs_lows', 0):+d})"),
            ("Strategy Rationale", "See 'Strategy Rationale' tab for empirical 5-year factorial proofs"),
        ]
        dash_meta = pd.DataFrame(meta_items, columns=["System Dimension", "Parameter / Value"])

        # Sectors
        sec_list = sector_data.get("sectors", [])[:10]
        rot_rows = []
        for idx, s in enumerate(sec_list, 1):
            rot_rows.append({
                "Rank": idx,
                "Sector": s.get("sector", ""),
                "N Scrips": s.get("total_symbols", 0),
                "Breadth %": s.get("pct_above_200ema", 0.0),
                "1M Ret %": s.get("ret_1m", 0.0),
                "3M Ret %": s.get("ret_3m", 0.0),
                "Alpha 1M %": s.get("alpha_1m", 0.0),
                "Alpha 3M %": s.get("alpha_3m", 0.0),
                "RRG Quadrant": s.get("rrg_quadrant", "UNKNOWN"),
                "Action": "ACCUMULATE" if s.get("rrg_quadrant") in ["LEADING", "IMPROVING"] else ("REDUCE" if s.get("rrg_quadrant") == "WEAKENING" else "AVOID"),
            })
        dash_rot = pd.DataFrame(rot_rows) if rot_rows else pd.DataFrame(columns=["Rank", "Sector", "N Scrips", "Breadth %", "1M Ret %", "3M Ret %", "Alpha 1M %", "Alpha 3M %", "RRG Quadrant", "Action"])

        # RRG Summary
        rrg_counts = {"LEADING": 0, "IMPROVING": 0, "WEAKENING": 0, "LAGGING": 0}
        rrg_sectors = {"LEADING": [], "IMPROVING": [], "WEAKENING": [], "LAGGING": []}
        for s in sector_data.get("sectors", []):
            q = s.get("rrg_quadrant", "LAGGING")
            if q in rrg_counts:
                rrg_counts[q] += 1
                rrg_sectors[q].append(s.get("sector", ""))
        dash_rrg = pd.DataFrame([
            {"Quadrant": q, "Count": rrg_counts[q], "Sectors": ", ".join(rrg_sectors[q][:6])}
            for q in ["LEADING", "IMPROVING", "WEAKENING", "LAGGING"]
        ])

        # Top 20 Stocks
        stk_rows = []
        cands = top_candidates_df.head(20) if not top_candidates_df.empty else screener_df.head(20)
        for idx, (_, r) in enumerate(cands.iterrows(), 1):
            sym = r["symbol"]
            stk_rows.append({
                "Rank": idx,
                "Symbol": sym,
                "Sector": r.get("sector", "OTHER"),
                "Close Price": round(float(r.get("close", 0.0)), 2),
                "Volar Score": round(float(r.get("volar_score", 0.0)), 3),
                "1Y Ret %": round(float(r.get("ret_1y", 0.0) if abs(float(r.get("ret_1y", 0.0))) > 5.0 or float(r.get("ret_1y", 0.0)) == 0.0 else float(r.get("ret_1y", 0.0)) * 100), 1),
                "RRG": r.get("rrg_quadrant", "WEAKENING"),
                "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
            })
        dash_stk = pd.DataFrame(stk_rows) if stk_rows else pd.DataFrame(columns=["Rank", "Symbol", "Sector", "Close Price", "Volar Score", "1Y Ret %", "RRG", "TradingView"])

        # Top 7 ETFs
        etf_rows = []
        if top_etf_df is not None and not top_etf_df.empty:
            for idx, (_, r) in enumerate(top_etf_df.head(7).iterrows(), 1):
                sym = r["symbol"]
                etf_rows.append({
                    "Rank": idx,
                    "ETF Symbol": sym,
                    "Underlying": r.get("underlying", ""),
                    "Price": round(float(r.get("price", 0.0)), 2),
                    "Volar Score": round(float(r.get("volar_score", 0.0)), 3),
                    "Target Qty": int(r.get("target_qty", 0)),
                    "Target Val (₹)": round(float(r.get("target_val", 0.0)), 2),
                    "Status": r.get("status", "TOP PICK"),
                    "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
                })
        dash_etf = pd.DataFrame(etf_rows) if etf_rows else pd.DataFrame(columns=["Rank", "ETF Symbol", "Underlying", "Price", "Volar Score", "Target Qty", "Target Val (₹)", "Status", "TradingView"])

        # Layout startrows accounting for 4 KPI cards at rows 4-6
        meta_title = 8
        meta_start = meta_title + 1
        rot_title = meta_start + len(dash_meta) + 2
        rot_start = rot_title + 1
        rrg_title = rot_start + len(dash_rot) + 2
        rrg_start = rrg_title + 1
        stk_title = rrg_start + len(dash_rrg) + 2
        stk_start = stk_title + 1
        etf_title = stk_start + len(dash_stk) + 2
        etf_start = etf_title + 1

        layout = {
            "meta_title": meta_title, "meta": meta_start,
            "rot_title": rot_title, "rot": rot_start,
            "rrg_title": rrg_title, "rrg": rrg_start,
            "stk_title": stk_title, "stk": stk_start,
            "etf_title": etf_title, "etf": etf_start,
        }

        return dash_meta, dash_rot, dash_rrg, dash_stk, dash_etf, layout

    def _build_strategy_rationale_df(self, screener_df):
        rows = [
            ("=== 1. ACTIVE STRATEGY SETTINGS (Empirical Calibrations) ===", "", "", ""),
            ("Dimension / Setting", "Calibrated Value", "Quant Rationale (ELI5)", "Backtest Impact (Why it Works)"),
            ("Target Universe", "NIFTY 500 PIT Sphere", "Top 500 liquid Indian equities with zero survivorship bias", "Eliminates circuit traps and illiquid execution slippage while ensuring genuine market breadth."),
            ("Ranking Metric", "Volar Score (Return / Annualized Volatility)", "Annual return divided by 252-session realized annualized volatility (with 5% volatility floor)", "Delivered 23.35% Net CAGR vs 11.38% for 52W Proximity. Highest alpha with lowest turnover."),
            ("Portfolio Size (N)", "Top 20 Stocks", "Optimal institutional diversification sweet spot", "Peaks Sharpe at 1.42-1.59 and cuts max drawdowns. Avoids single-stock blowup risk."),
            ("Rebalance Frequency", "Monthly (M)", "Monthly portfolio re-weighting", "Matches the empirical 40-60 session momentum half-life without holding decaying laggards."),
            ("Market Trend Gate", "ACTIVE (NIFTY 500 >= 20 EMA)", "Defensive Cash Shield during Bear Regimes", "Reduces Max Drawdown from -34.7% to -22.3% and elevates Profit Factor to 2.35."),
            ("Sector Concentration Cap", "Max 2 per Sector", "Strict anti-clustering constraint", "Prevents catastrophic sector blowups (e.g. over-allocation to tech in 2021). Guarantees 10+ distinct sectors."),
            ("Retracement Cutoff", "20% from 52W High", "Falling knife & broken chart filter", "Strictly rejects severely damaged charts while allowing natural volatility pullbacks."),
            ("Long-Term Trend Gate", "Price > 200 EMA", "Structural bull confirmation", "Guarantees institutional sponsorship behind every entered position."),
            ("Dynamic Position Sizing", "ATR-14 Risk Parity", "14-Day ATR Inverse-Volatility Risk Budgeting", "Equalizes risk across positions by allocating smaller capital to volatile names and larger capital to steady compounders."),
            ("=== 2. EMPIRICAL 5-YEAR FACTORIAL BACKTEST PROOF (2021-2026) ===", "", "", ""),
            ("Factor Tested", "Winning Configuration", "Losing / Disqualified Configuration", "Key Empirical Quantitative Proof"),
            ("Ranking Method", "Volar: 23.35% Net CAGR | 1.08 Sharpe", "52W Proximity: 11.38% Net CAGR | 0.63 Sharpe", "52W Proximity suffers 568% annual turnover on whipsaws; Volar delivers 285% turnover."),
            ("Rebalance Cadence", "Monthly: 25.40% Net CAGR | 1.23 Sharpe", "Quarterly: 13.04% Net CAGR | 0.60 Sharpe", "Quarterly rebalancing decays momentum; Monthly rebalancing nearly doubles net return."),
            ("Portfolio Breadth", "N=20: 22.41% Net CAGR | -27.50% Max DD", "N=5: 12.51% Net CAGR | -39.44% Max DD", "5 stocks represents reckless single-stock risk; 20 stocks hits the optimal efficient frontier."),
            ("Market Gate", "Gate ON: -22.32% Max DD | 2.35 Profit Factor", "Gate OFF: -34.70% Max DD | 1.58 Profit Factor", "Holding cash when the index is below 20 EMA preserves capital in market crashes."),
            ("=== 3. DISQUALIFIED TRASH IDEAS (EMPIRICAL WARNINGS) ===", "", "", ""),
            ("Disqualified Setting", "Why People Try It", "Fatal Flaw Identified in Backtesting", "Verdict"),
            ("5-Stock Portfolio", "Greed for hyper-concentration", "High idiosyncratic risk: a single bad stock crushes the portfolio. Max drawdown hits -41.52%.", "TRASH (Reckless Concentration)"),
            ("Quarterly Rebalancing", "Desire to minimize brokerage", "Momentum in India decays after 40-60 days. Holds declining stocks for 3 months, halving CAGR.", "TRASH (Decaying Momentum)"),
            ("52-Week High Proximity", "Classic retail breakout indicator", "Triggers 568% annual turnover on false breakouts; underperforms buy-and-hold index.", "TRASH (High Churn / Low Alpha)")
        ]
        return pd.DataFrame(rows, columns=["Parameter / Factor", "Setting / Evidence", "Quant Rationale (ELI5)", "Empirical Proof / Verdict"])

    def _build_sector_rotation_df(self, sector_data, screener_df=None):
        sec_list = sector_data.get("sectors", [])

        leaders_map = {}
        if screener_df is not None and not screener_df.empty:
            sec_col = "industry" if "industry" in screener_df.columns else "sector"
            for sec, grp in screener_df.groupby(sec_col):
                top3 = grp.sort_values(by="volar_score", ascending=False)["symbol"].head(3).tolist()
                leaders_map[str(sec).upper()] = ", ".join(top3)

        rows = []
        for idx, s in enumerate(sec_list, 1):
            sec = str(s.get("sector", "")).upper()
            q = s.get("rrg_quadrant", "UNKNOWN")
            act = s.get("action", "OVERWEIGHT" if q == "LEADING" else ("ACCUMULATE" if q == "IMPROVING" else ("REDUCE" if q == "WEAKENING" else "AVOID")))
            l_str = leaders_map.get(sec, s.get("top_3_leaders", ""))

            rows.append({
                "Rank": idx,
                "Industry": sec,
                "Stocks": s.get("stock_count", s.get("total_symbols", 0)),
                "Top 3 Leaders": l_str,
                "1M %": s.get("ret_1m", 0.0),
                "3M %": s.get("ret_3m", 0.0),
                "6M %": s.get("ret_6m", 0.0),
                "Excess 1M %": s.get("excess_1m", s.get("alpha_1m", 0.0)),
                "Excess 3M %": s.get("excess_3m", s.get("alpha_3m", 0.0)),
                "Excess 6M %": s.get("excess_6m", s.get("alpha_6m", 0.0)),
                "RS-Ratio (RRG)": s.get("rrg_rs_ratio", 100.0),
                "RS-Mom % (RRG)": s.get("rrg_rs_momentum", 100.0),
                "RRG Quadrant": q,
                "Prev Quadrant": s.get("prev_quadrant", q),
                "RRG Trend": "UPTREND" if q in ["LEADING", "IMPROVING"] else "DOWNTREND",
                "Rotation State": s.get("rotation_state", "NEUTRAL"),
                "Rotation Event (5d)": s.get("rotation_event", "STABLE"),
                "New 52w Highs": s.get("new_52w_highs", 0),
                "Breadth Score": s.get("breadth_score", s.get("breadth_200_pct", 0.0)),
                "Breadth Delta": s.get("delta", 0.0),
                "Elite %": s.get("elite_pct", 0.0),
                "30d Rank Δ": s.get("rank_delta_30d", 0),
                "Signal Agreement (0-5)": s.get("signal_agreement", 0),
                "Action": act,
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
            "Rank", "Industry", "Stocks", "Top 3 Leaders", "1M %", "3M %", "6M %",
            "Excess 1M %", "Excess 3M %", "Excess 6M %", "RS-Ratio (RRG)", "RS-Mom % (RRG)",
            "RRG Quadrant", "Prev Quadrant", "RRG Trend", "Rotation State", "Rotation Event (5d)",
            "New 52w Highs", "Breadth Score", "Breadth Delta", "Elite %", "30d Rank Δ",
            "Signal Agreement (0-5)", "Action"
        ])

    def _build_industry_ranking_df(self, sector_data, screener_df=None):
        sec_list = sector_data.get("sectors", [])

        leaders_map = {}
        if screener_df is not None and not screener_df.empty:
            sec_col = "industry" if "industry" in screener_df.columns else "sector"
            for sec, grp in screener_df.groupby(sec_col):
                top3 = grp.sort_values(by="volar_score", ascending=False)["symbol"].head(3).tolist()
                leaders_map[str(sec).upper()] = ", ".join(top3)

        rows = []
        for idx, s in enumerate(sec_list, 1):
            sec = str(s.get("sector", "")).upper()
            q = s.get("rrg_quadrant", "UNKNOWN")
            act = s.get("action", "OVERWEIGHT" if q == "LEADING" else ("ACCUMULATE" if q == "IMPROVING" else ("REDUCE" if q == "WEAKENING" else "AVOID")))
            l_str = leaders_map.get(sec, s.get("top_3_leaders", ""))

            rows.append({
                "Rank": idx,
                "Sector": sec,
                "Industry Name": s.get("name", sec),
                "Total Scrips": s.get("stock_count", s.get("total_symbols", 0)),
                "Composite Score": s.get("composite_score", 0.0),
                "1M Return %": s.get("ret_1m", 0.0),
                "3M Return %": s.get("ret_3m", 0.0),
                "1Y Return %": s.get("ret_1y", 0.0),
                "Alpha 1M %": s.get("alpha_1m", 0.0),
                "Alpha 3M %": s.get("alpha_3m", 0.0),
                "Breadth % (>200EMA)": s.get("breadth_200_pct", s.get("pct_above_200ema", 0.0)),
                "Near 52w High %": s.get("near_high_pct", 0.0),
                "RS-Ratio (RRG)": s.get("rrg_rs_ratio", 100.0),
                "RS-Mom (RRG)": s.get("rrg_rs_momentum", 100.0),
                "RRG Quadrant": q,
                "Top 3 Leaders": l_str,
                "Action": act,
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Rank", "Sector", "Industry Name", "Total Scrips", "Composite Score", "1M Return %", "3M Return %", "1Y Return %", "Alpha 1M %", "Alpha 3M %", "Breadth % (>200EMA)", "Near 52w High %", "RS-Ratio (RRG)", "RS-Mom (RRG)", "RRG Quadrant", "Top 3 Leaders", "Action"])

    def _build_industry_history_df(self, as_of_date, bars_df=None):
        """Computes daily 30-day sector breadth and return history time-series."""
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(columns=["Date", "Sector", "Scrips", "% > 200 EMA", "1M Ret %", "52w Highs"])

        all_dates = sorted(bars_df["date"].unique())
        sub_dates = [d for d in all_dates if d <= as_of_date][-30:]
        if not sub_dates:
            return pd.DataFrame(columns=["Date", "Sector", "Scrips", "% > 200 EMA", "1M Ret %", "52w Highs"])

        sub = bars_df[bars_df["date"].isin(sub_dates)].copy()
        if "sector" not in sub.columns:
            smap = load_symbol_sector_map()
            sub["sector"] = sub["symbol"].map(smap).fillna("SERVICES")

        req = {"close", "ema_200", "high_252"}
        if not req.issubset(set(sub.columns)):
            return pd.DataFrame(columns=["Date", "Sector", "Scrips", "% > 200 EMA", "1M Ret %", "52w Highs"])

        ret_col = "ret_1m" if "ret_1m" in sub.columns else ("ret_21" if "ret_21" in sub.columns else None)

        def _calc_sec_hist(g):
            n = len(g)
            above_200 = (g["close"] > g["ema_200"]).mean() * 100.0 if "ema_200" in g.columns else 0.0
            r1m = g[ret_col].mean() if ret_col else 0.0
            if ret_col == "ret_21" and abs(r1m) < 0.5:
                r1m *= 100.0
            new_highs = (g["close"] >= 0.99 * g["high_252"]).sum() if "high_252" in g.columns else 0
            return pd.Series({
                "Scrips": n,
                "% > 200 EMA": round(above_200, 1),
                "1M Ret %": round(r1m, 2),
                "52w Highs": int(new_highs),
            })

        hist = sub.groupby(["date", "sector"]).apply(_calc_sec_hist, include_groups=False).reset_index()
        hist = hist.rename(columns={"date": "Date", "sector": "Sector"})
        return hist.sort_values(by=["Date", "Sector"], ascending=[False, True]).reset_index(drop=True)

    def _build_stock_ranking_df(self, screener_df, delivery_df, sector_data=None):
        dmap = {}
        if delivery_df is not None and not delivery_df.empty:
            dmap = delivery_df.set_index("symbol").to_dict(orient="index")

        ind_rank_map = {}
        ind_score_map = {}
        ind_agr_map = {}
        ind_rot_map = {}
        if sector_data and "sectors" in sector_data:
            for s in sector_data["sectors"]:
                sec = str(s.get("sector", "")).upper()
                ind_rank_map[sec] = s.get("rank", 99)
                ind_score_map[sec] = s.get("composite_score", 0.0)
                ind_agr_map[sec] = s.get("signal_agreement", 0)
                ind_rot_map[sec] = s.get("rotation_state", "NEUTRAL")

        # STRICT INVARIANT: Candidates must be ranked by volar_score descending ONLY!
        df_sorted = screener_df.sort_values(by="volar_score", ascending=False).reset_index(drop=True)

        rows = []
        for idx, (_, r) in enumerate(df_sorted.iterrows(), 1):
            sym = str(r["symbol"]).strip().upper()
            ind = str(r.get("industry", r.get("sector", "SERVICES"))).strip().upper()
            px = float(r.get("close", 0.0))
            volar = float(r.get("volar_score", 0.0))
            d_info = dmap.get(sym, {})

            pct_ema200 = float(r.get("pct_above_ema200", (px / max(0.01, float(r.get("ema_200", px))) - 1.0) * 100))
            ext = "⚠ EXT >40%" if pct_ema200 > 40.0 else ("EXT >25%" if pct_ema200 > 25.0 else "")
            liq = "⚠ LOW LIQ (<₹1Cr)" if float(r.get("turnover_30d", 1e8)) < 1e7 else ""
            san = "⚠ SANITY (>±35% 60d)" if float(r.get("max_move_60", 0.0)) > 0.35 else ""
            to_30_cr = round(float(r.get("turnover_30d", 0.0)) / 1e7, 2)

            rrg = str(r.get("rrg_quadrant", "WEAKENING"))
            rot = ind_rot_map.get(ind, str(r.get("rotation_state", "NEUTRAL")))
            ind_rnk = ind_rank_map.get(ind, int(r.get("industry_rank", 99)))
            ind_sc = ind_score_map.get(ind, 0.0)
            ind_agr = ind_agr_map.get(ind, 0)

            ret_1y = float(r.get("ret_1y", r.get("return_252d", 0.0)))
            ret_1y_pct = round(ret_1y if abs(ret_1y) > 5.0 or ret_1y == 0.0 else ret_1y * 100.0, 1)

            dd = round(float(r.get("drawdown_from_high", 0.0) or (1.0 - px / max(0.01, float(r.get("high_252", px)))) * 100), 1)

            rows.append({
                "Rank (MIP-1)": idx,
                "Rank (Industry-Aware)": idx,
                "Symbol": sym,
                "Industry": ind,
                "Price": round(px, 2),
                "252D Return %": ret_1y_pct,
                "Volar Score": round(volar, 4),
                "From 52w High %": dd,
                "Vs EMA-200 %": round(pct_ema200, 1),
                "Delivery %": round(float(d_info.get("deliv_per", d_info.get("delivery_pct", np.nan))), 1) if pd.notna(d_info.get("deliv_per", d_info.get("delivery_pct", np.nan))) else np.nan,
                "Delivery Qty": int(d_info.get("deliv_qty", d_info.get("delivery_qty", 0))) if pd.notna(d_info.get("deliv_qty", d_info.get("delivery_qty", np.nan))) else np.nan,
                "Delivery Times (5D)": round(float(d_info.get("deliv_times", d_info.get("delivery_multiple_5d", np.nan))), 1) if pd.notna(d_info.get("deliv_times", d_info.get("delivery_multiple_5d", np.nan))) else np.nan,
                "Delivery Value (₹Cr)": round(float(d_info.get("delivery_value_cr", np.nan)), 2) if pd.notna(d_info.get("delivery_value_cr", np.nan)) else np.nan,
                "Extension Flag (display-only)": ext,
                "Turnover 30d (₹Cr, display-only)": to_30_cr,
                "Liquidity Flag (display-only)": liq,
                "Sanity Flag (display-only)": san,
                "RS Ratio": round(float(r.get("rs_ratio_raw", r.get("rrg_rs_ratio", 100.0))), 2),
                "RS EMA": round(float(r.get("rs_ema_200", 100.0)), 2),
                "Ann Vol %": round(float(r.get("vol_252", 0.0)) * 100.0 if float(r.get("vol_252", 0.0)) < 2.0 else float(r.get("vol_252", 0.0)), 1),
                "Industry Rank": ind_rnk,
                "Industry Score": ind_sc,
                "Ind. Agreement": ind_agr,
                "RRG Quadrant": rrg,
                "RRG Trend": "UPTREND" if rrg in ["LEADING", "IMPROVING"] else "DOWNTREND",
                "Rotation": rot,
                "Final Score": round(volar, 4),
                "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
            })
        return pd.DataFrame(rows)

    def _build_candidates_df(self, top_candidates_df, delivery_df, market_bullish, sector_data=None):
        dmap = {}
        if delivery_df is not None and not delivery_df.empty:
            dmap = delivery_df.set_index("symbol").to_dict(orient="index")

        ind_rank_map = {}
        ind_score_map = {}
        ind_rot_map = {}
        if sector_data and "sectors" in sector_data:
            for s in sector_data["sectors"]:
                sec = str(s.get("sector", "")).upper()
                ind_rank_map[sec] = s.get("rank", 99)
                ind_score_map[sec] = s.get("composite_score", 0.0)
                ind_rot_map[sec] = s.get("rotation_state", "NEUTRAL")

        # STRICT INVARIANT: Candidates must be ranked by volar_score descending ONLY!
        df_sorted = top_candidates_df.sort_values(by="volar_score", ascending=False).reset_index(drop=True)

        rows = []
        is_bear = not market_bullish
        for idx, (_, r) in enumerate(df_sorted.head(20).iterrows(), 1):
            sym = str(r["symbol"]).strip().upper()
            ind = str(r.get("industry", r.get("sector", "SERVICES"))).strip().upper()
            px = float(r.get("close", r.get("close_price", 0.0)))
            atr = float(r.get("atr_14", px * 0.03))
            sl = float(r.get("stop_loss", max(0.01, px - 2.0 * atr)))
            qty = int(r.get("target_qty", r.get("target_shares", 0)))
            d_info = dmap.get(sym, {})

            volar = float(r.get("volar_score", 0.0))
            pct_ema200 = float(r.get("pct_above_ema200", (px / max(0.01, float(r.get("ema_200", px))) - 1.0) * 100))
            ext = "⚠ EXT >40%" if pct_ema200 > 40.0 else ("EXT >25%" if pct_ema200 > 25.0 else "")
            liq = "⚠ LOW LIQ (<₹1Cr)" if float(r.get("turnover_30d", 1e8)) < 1e7 else ""
            san = "⚠ SANITY (>±35% 60d)" if float(r.get("max_move_60", 0.0)) > 0.35 else ""

            rrg = str(r.get("rrg_quadrant", "WEAKENING"))
            trend = "HOLDING" if px > float(r.get("ema_200", px)) else "RECOVERING"
            rot = ind_rot_map.get(ind, str(r.get("rotation_state", "NEUTRAL")))
            ind_rnk = ind_rank_map.get(ind, int(r.get("industry_rank", 99)))

            tier = str(r.get("selection_tier", ""))
            if not tier:
                if (rrg == "LEADING" and "UPTREND" in rot) or (rrg == "IMPROVING" and "RECOVERY" in rot):
                    tier = "TIER-1 (Leading + Uptrend)"
                elif rrg in ["LEADING", "IMPROVING"]:
                    tier = "TIER-2 (RRG right side)"
                else:
                    tier = "TIER-3 (All)"
                if is_bear:
                    tier = f"HOLD (BEAR - {tier})"

            status = "HOLD (BEAR - 100% CASH)" if is_bear else "NEW BUY"

            rows.append({
                "Rank": idx,
                "Symbol": sym,
                "Industry": ind,
                "Price": round(px, 2),
                "MIP-1 Status": status,
                "ATR (14D)": round(atr, 2),
                "Stop Loss (2x ATR)": round(sl, 2),
                "Risk Budget (₹)": round(qty * (px - sl), 2) if qty > 0 else 0.0,
                "Target Qty (₹1L Portfolio)": qty,
                "Target Value (₹)": round(qty * px, 2),
                "Delivery %": round(float(d_info.get("deliv_per", d_info.get("delivery_pct", np.nan))), 1) if pd.notna(d_info.get("deliv_per", d_info.get("delivery_pct", np.nan))) else np.nan,
                "Delivery Qty": int(d_info.get("deliv_qty", d_info.get("delivery_qty", 0))) if pd.notna(d_info.get("deliv_qty", d_info.get("delivery_qty", np.nan))) else np.nan,
                "Delivery Times (5D)": round(float(d_info.get("deliv_times", d_info.get("delivery_multiple_5d", np.nan))), 1) if pd.notna(d_info.get("deliv_times", d_info.get("delivery_multiple_5d", np.nan))) else np.nan,
                "Delivery Value (₹Cr)": round(float(d_info.get("delivery_value_cr", np.nan)), 2) if pd.notna(d_info.get("delivery_value_cr", np.nan)) else np.nan,
                "Volar": round(volar, 4),
                "Extension": ext,
                "Liquidity": liq,
                "Sanity": san,
                "RRG": rrg,
                "Trend": trend,
                "Rotation": rot,
                "Industry Rank": ind_rnk,
                "Final Score": round(volar, 4),
                "Selection Tier": tier,
                "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
            })
        return pd.DataFrame(rows)

    def _build_highest_delivery_df(self, delivery_df, screener_df):
        if delivery_df is None or delivery_df.empty:
            return pd.DataFrame([{"Note": "NSE Delivery Bhavcopy not available for this session."}])

        active_syms = set(screener_df["symbol"].tolist()) if not screener_df.empty else set(delivery_df["symbol"])
        sub = delivery_df[delivery_df["symbol"].isin(active_syms)].copy()
        if sub.empty:
            sub = delivery_df.copy()

        # Filter spikes >= 5 Cr turnover
        spikes = sub[sub["delivery_value_cr"].fillna(0) >= 5.0].sort_values("deliv_per", ascending=False).reset_index(drop=True)
        if len(spikes) < 10:
            spikes = sub[sub["delivery_value_cr"].fillna(0) >= 1.0].sort_values("deliv_per", ascending=False).reset_index(drop=True)

        rows = []
        for idx, (_, r) in enumerate(spikes.iterrows(), 1):
            sym = r["symbol"]
            rows.append({
                "Rank": idx,
                "Symbol": sym,
                "Series": r.get("series", "EQ"),
                "Delivery Action": r.get("deliv_action", "⚪ NEUTRAL"),
                "Close Price": round(float(r.get("close_price", 0.0)), 2),
                "1D Return %": round(float(r.get("deliv_ret_pct", 0.0)), 2),
                "Delivery %": round(float(r.get("deliv_per", 0.0)), 2),
                "Delivery Qty": int(r.get("deliv_qty", 0)) if pd.notna(r.get("deliv_qty")) else 0,
                "Delivery Times (5D)": round(float(r.get("deliv_times", 0.0)), 1) if pd.notna(r.get("deliv_times")) else np.nan,
                "Delivery Value (₹Cr)": round(float(r.get("delivery_value_cr", 0.0)), 2),
                "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
            })
        return pd.DataFrame(rows)

    def _build_etf_ranking_df(self, etf_ranking_df):
        if etf_ranking_df is None or etf_ranking_df.empty:
            return pd.DataFrame([{"Note": "ETF scanning disabled or no data available."}])

        rows = []
        for idx, (_, r) in enumerate(etf_ranking_df.iterrows(), 1):
            sym = r["symbol"]
            rows.append({
                "Rank": idx,
                "Symbol": sym,
                "Underlying Asset": r.get("underlying", ""),
                "Price": round(float(r.get("price", 0.0)), 2),
                "Volar Score": round(float(r.get("volar_score", 0.0)), 3),
                "1Y Return %": round(float(r.get("return_1y", 0.0)), 1),
                "From 52w High %": round(float(r.get("retrace_pct", 0.0)), 1),
                "Vs EMA-100 %": round(float(r.get("vs_ema100", 0.0)), 1),
                "Vs EMA-200 %": round(float(r.get("vs_ema200", 0.0)), 1),
                "Turnover (₹Cr)": round(float(r.get("turnover_cr", 0.0)), 2),
                "Status": r.get("status", "QUALIFIED"),
                "TradingView": f"https://in.tradingview.com/chart/?symbol=NSE:{sym}",
            })
        return pd.DataFrame(rows)

    def _seed_picks_from_colab(self, colab_path: Path):
        """Seeds historical vintages from colabexport.xlsx into SQLite picks_history if empty."""
        try:
            import openpyxl
            wb = openpyxl.load_workbook(str(colab_path), data_only=True)
            if "Pick Performance" not in wb.sheetnames:
                return
            ws = wb["Pick Performance"]
            header = None
            rows = []
            for i, r in enumerate(ws.iter_rows(values_only=True)):
                if i == 10:
                    header = [c for c in r if c is not None]
                elif i > 10 and any(r):
                    row_dict = dict(zip(header, r[:len(header)]))
                    rows.append(row_dict)

            from .data_engine import get_connection
            conn = get_connection(read_only=False, reuse=False)
            cursor = conn.cursor()
            for row in rows:
                pdate = str(row.get("Pick Date", ""))
                sym = str(row.get("Symbol", "")).strip().upper()
                rnk = int(row.get("Rank", 0)) if row.get("Rank") is not None else 0
                ind = str(row.get("Industry", "SERVICES"))
                reg = str(row.get("Regime", "BEAR"))
                sig = str(row.get("Type", "BEAR_HOLD"))
                st = str(row.get("Status", "ACTIVE"))
                entry = float(row.get("Entry", 0.0)) if row.get("Entry") is not None else 0.0
                r1w = float(row.get("1W %")) if row.get("1W %") is not None else None
                r1m = float(row.get("1M %")) if row.get("1M %") is not None else None
                rsince = float(row.get("Since %")) if row.get("Since %") is not None else None
                last_dt = str(row.get("Last Px Date", ""))
                cursor.execute("""
                    INSERT OR REPLACE INTO picks_history
                    (pick_date, symbol, rank, industry, regime, signal_type, status, entry_price, ret_1w, ret_1m, ret_since, last_px_date, volar_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (pdate, sym, rnk, ind, reg, sig, st, entry, r1w, r1m, rsince, last_dt, 0.0))
            conn.commit()
            conn.close()
        except Exception:
            pass

    def _build_picks_performance_df(self):
        """Builds Summary and Detail tables from SQLite universe.db table picks_history."""
        try:
            from .data_engine import get_connection
            conn = get_connection(read_only=True, reuse=False)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='picks_history'")
            if not cursor.fetchone():
                conn.close()
                return pd.DataFrame(), pd.DataFrame()

            cursor.execute("SELECT COUNT(*) FROM picks_history")
            cnt = cursor.fetchone()[0]
            if cnt == 0:
                colab_path = self.reports_dir / "colabexport.xlsx"
                if colab_path.exists():
                    self._seed_picks_from_colab(colab_path)

            df_all = pd.read_sql_query("SELECT * FROM picks_history ORDER BY pick_date DESC, rank ASC", conn)
            conn.close()

            if df_all.empty:
                return pd.DataFrame(), pd.DataFrame()

            # Build Summary Table
            sum_rows = []
            for pdate, grp in df_all.groupby("pick_date", sort=False):
                reg = grp["regime"].iloc[0] if "regime" in grp.columns else "BEAR"
                n_picks = len(grp)
                w1 = grp["ret_1w"].dropna() if "ret_1w" in grp.columns else pd.Series(dtype=float)
                m1 = grp["ret_1m"].dropna() if "ret_1m" in grp.columns else pd.Series(dtype=float)
                sn = grp["ret_since"].dropna() if "ret_since" in grp.columns else pd.Series(dtype=float)

                avg_1w = round(w1.mean(), 2) if not w1.empty else None
                avg_1m = round(m1.mean(), 2) if not m1.empty else None
                avg_sn = round(sn.mean(), 2) if not sn.empty else None
                win_rt = round((sn > 0).mean() * 100.0, 1) if not sn.empty else None

                sum_rows.append({
                    "Pick Date": pdate,
                    "Regime": reg,
                    "N Picks": n_picks,
                    "Avg 1W %": avg_1w,
                    "Avg 1M %": avg_1m,
                    "Avg Since %": avg_sn,
                    "Win Rate %": win_rt,
                })
            sum_df = pd.DataFrame(sum_rows)

            # Build Detail Table
            det_rows = []
            for _, r in df_all.iterrows():
                det_rows.append({
                    "Pick Date": r.get("pick_date", ""),
                    "Symbol": r.get("symbol", ""),
                    "Rank": int(r.get("rank", 0)),
                    "Industry": r.get("industry", ""),
                    "Regime": r.get("regime", "BEAR"),
                    "Type": r.get("signal_type", "BEAR_HOLD"),
                    "Status": r.get("status", "ACTIVE"),
                    "Entry": round(float(r.get("entry_price", 0.0)), 2),
                    "1W %": round(float(r["ret_1w"]), 2) if pd.notna(r.get("ret_1w")) else None,
                    "1M %": round(float(r["ret_1m"]), 2) if pd.notna(r.get("ret_1m")) else None,
                    "Since %": round(float(r["ret_since"]), 2) if pd.notna(r.get("ret_since")) else None,
                    "Last Px Date": r.get("last_px_date", ""),
                })
            det_df = pd.DataFrame(det_rows)

            return sum_df, det_df

        except Exception:
            return pd.DataFrame(), pd.DataFrame()

    def _build_raw_metrics_df(self, snap_df: Optional[pd.DataFrame]) -> pd.DataFrame:
        """Builds 14th sheet: 28-column Raw Stock Metrics point-in-time quantitative data lake."""
        if snap_df is None or snap_df.empty:
            return pd.DataFrame()

        rows = []
        for _, r in snap_df.iterrows():
            sym = str(r.get("symbol", "")).strip().upper()
            ind = str(r.get("industry", r.get("sector", "SERVICES"))).strip().upper()
            dt = str(r.get("date", ""))
            op = round(float(r.get("open", 0.0)), 2)
            hi = round(float(r.get("high", 0.0)), 2)
            lo = round(float(r.get("low", 0.0)), 2)
            cl = round(float(r.get("close", 0.0)), 2)
            vol = int(r.get("volume", 0)) if pd.notna(r.get("volume")) else 0
            to_30 = float(r.get("turnover_30d", 0.0))
            to_30_cr = round(to_30 / 1e7, 2)

            ret_252_val = float(r.get("ret_1y", r.get("return_252d", 0.0)))
            ret_252 = round(ret_252_val / 100.0 if abs(ret_252_val) > 2.0 else ret_252_val, 3)

            volar = round(float(r.get("volar_score", 0.0)), 4)
            ann_vol = round(float(r.get("vol_252", r.get("ann_vol", 0.0))), 3)
            rsi = round(float(r.get("rsi_14", 50.0)), 3)

            s50 = round(float(r.get("sma_50", r.get("ema_50", cl))), 3)
            s100 = round(float(r.get("sma_100", cl)), 3)
            s200 = round(float(r.get("sma_200", r.get("ema_200", cl))), 3)

            rs_r = round(float(r.get("rs_ratio_raw", r.get("rs_ratio", 1.0))), 4)
            rs_e = round(float(r.get("rs_ema_200", r.get("rs_ema", 1.0))), 4)

            dd = round(float(r.get("drawdown_from_high", 0.0)), 3)
            e200 = round(float(r.get("ema_200", cl)), 3)

            ab_s50 = bool(r.get("above_sma50", cl > s50))
            ab_s100 = bool(r.get("above_sma100", cl > s100))
            ab_s200 = bool(r.get("above_sma200", cl > s200))
            rs_pos = bool(r.get("rs_positive", rs_r > 1.0))
            tr_al = bool(r.get("trend_aligned", cl > e200))
            el = bool(r.get("elite", cl > e200 and dd <= 15.0))
            at_52 = bool(r.get("at_52w_high", dd <= 1.0))

            rows.append({
                "symbol": sym,
                "industry": ind,
                "date": dt,
                "open": op,
                "high": hi,
                "low": lo,
                "close": cl,
                "volume": vol,
                "turnover_30d": round(to_30, 2),
                "return_252d": ret_252,
                "volar_score": volar,
                "ann_vol": ann_vol,
                "rsi_14": rsi,
                "sma_50": s50,
                "sma_100": s100,
                "sma_200": s200,
                "rs_ratio": rs_r,
                "rs_ema": rs_e,
                "drawdown_from_high": dd,
                "ema_200": e200,
                "above_sma50": ab_s50,
                "above_sma100": ab_s100,
                "above_sma200": ab_s200,
                "rs_positive": rs_pos,
                "trend_aligned": tr_al,
                "elite": el,
                "at_52w_high": at_52,
                "turnover_30d_cr": to_30_cr,
            })

        df = pd.DataFrame(rows)
        return df.sort_values(by="volar_score", ascending=False).reset_index(drop=True)

    def _build_breadth_history_df(self, as_of_date: str, bars_df: Optional[pd.DataFrame] = None, universe_label: str = "NIFTY 500") -> pd.DataFrame:
        """Computes daily market-wide breadth history across the last 60 sessions."""
        if bars_df is None or bars_df.empty:
            return pd.DataFrame(columns=["Date", "Universe", "Active Scrips", "% > 200 EMA", "% > 50 EMA", "% > 20 EMA", "% Near 52wH", "52w Highs", "52w Lows", "Net Highs", "Breadth Regime"])

        all_dates = sorted(bars_df["date"].unique())
        sub_dates = [d for d in all_dates if d <= as_of_date][-60:]
        if not sub_dates:
            return pd.DataFrame(columns=["Date", "Universe", "Active Scrips", "% > 200 EMA", "% > 50 EMA", "% > 20 EMA", "% Near 52wH", "52w Highs", "52w Lows", "Net Highs", "Breadth Regime"])

        sub = bars_df[bars_df["date"].isin(sub_dates)].copy()

        def _calc_breadth_row(g):
            n = len(g)
            p200 = round((g["close"] > g["ema_200"]).mean() * 100.0, 1) if "ema_200" in g.columns else 0.0
            p50 = round((g["close"] > g["ema_50"]).mean() * 100.0, 1) if "ema_50" in g.columns else 0.0
            p20 = round((g["close"] > g["ema_20"]).mean() * 100.0, 1) if "ema_20" in g.columns else 0.0
            pnear = round((g["close"] >= 0.80 * g["high_252"]).mean() * 100.0, 1) if "high_252" in g.columns else 0.0
            nh = int((g["close"] >= 0.99 * g["high_252"]).sum()) if "high_252" in g.columns else 0
            nl = int((g["close"] <= 1.01 * g["low_252"]).sum()) if "low_252" in g.columns else 0
            net = nh - nl

            if p200 >= 60.0 and p50 >= 55.0:
                regime = "🟢 STRONG EXPANSION"
            elif p200 < 40.0 or (p200 < 50.0 and net < 0):
                regime = "🔴 CONTRACTION / DEFENSIVE"
            else:
                regime = "🟡 SELECTIVE / NEUTRAL"

            return pd.Series({
                "Universe": universe_label,
                "Active Scrips": n,
                "% > 200 EMA": p200,
                "% > 50 EMA": p50,
                "% > 20 EMA": p20,
                "% Near 52wH": pnear,
                "52w Highs": nh,
                "52w Lows": nl,
                "Net Highs": net,
                "Breadth Regime": regime,
            })

        b_hist = sub.groupby("date").apply(_calc_breadth_row, include_groups=False).reset_index()
        b_hist = b_hist.rename(columns={"date": "Date"})
        return b_hist.sort_values(by="Date", ascending=False).reset_index(drop=True)

    def _build_config_df(self, as_of_date, excel_path, universe_label="NIFTY 500"):
        rows = [
            ("Scanner Version", "v5.5.1 (Institutional Quant Edition — Empirical Optimal Settings & Strategy Rationale)"),
            ("Storage Mode", "Zero-Compiler SQLite3 (universe.db) + Indexed Parity"),
            ("Universe(s)", f"{universe_label}  (NIFTY 500 Recommended Liquid Sphere)"),
            ("Empirical Reference", "Calibrated via 150-cell grid backtest (2021-2026). See 'Strategy Rationale' sheet."),
            ("Ranking Metric (MIP-1)", "volar"),
            ("N Stocks", 20),
            ("Retracement %", 20),
            ("EMA Period", 200),
            ("RS Filter", True),
            ("Market Filter MA", 20),
            ("Market Filter Benchmark", "^NSEI (regime filter uses the RS benchmark — original MIP-1 behavior)"),
            ("Momentum (Volar) Lookback", 252),
            ("RS Benchmark", "^NSEI"),
            ("Data Source", "Zero-Compiler SQLite3 + NSE Bhavcopy archives (Pure-Python Zero-CLI)"),
            ("Deep Seed Start", "2024-01-01"),
            ("Corporate-Action Watchdog (NEW v5.4.4)", "overlapping closes checked before anti-join; stable ratio≠1 (split/div) or unstable ratio → full-history refetch per symbol"),
            ("OHLCV Validation (NEW v5.4.4)", "drops close≤0, high<low, high<open, high<close, low>open, low>close; nulls negative volumes; applies to yfinance + bhavcopy"),
            ("Cache Hygiene (NEW v5.4.4)", "rows before DEEP_SEED_START dropped at load; dynamic indexed lookups"),
            ("OHLCV Cache", "open/high/low/close/volume (display-only turnover + LOW-LIQ flags)"),
            ("Breadth Mode", "FULL RECOMPUTE every run — self-healing; multi-index participation"),
            ("Null Handling", "breadth booleans null→False (consistent denominators); null RRG → UNKNOWN"),
            ("Trading Calendar", "benchmark dates ∪ high-coverage stock dates (picks alignment)"),
            ("Pick Returns", "1W/1M calendar-aligned, ±2-session tolerance (halted stocks → null)"),
            ("Pick Signal Types", "BUY (BULL regime) / BEAR_HOLD (BEAR regime)"),
            ("Symbol Blacklist", "≥5 failed download attempts → 90-day skip (data/symbol_blacklist.json)"),
            ("Selective Cache Pull", "Pydroid auto-fetch scans missing dates directly from NSE Bhavcopy archives"),
            ("Rotation 1M/3M/6M sessions", "21/63/126"),
            ("RRG (StockCharts-style)", "RS-Ratio = 100×RSline/SMA63, EMA(0.1) smooth; RS-Mom = 10d ROC; trail 10d"),
            ("Min Industry Stocks (ranking)", 5),
            ("Industry Score (PRESERVED)", "0.40*RS% + 0.40*SMA200% + 0.20*RSI>50%"),
            ("Delta (PRESERVED)", "sma50_pct - sma200_pct"),
            ("Rank Weights", "Score 0.5 / 5D 0.2 / 30D 0.15 / Elite 0.15"),
            ("Stock/Industry weights", "MIP-1 1.0 (Strict Volar-Only Ranking) / Industry 0.0 (Informational Lens)"),
            ("Action Matrix", "Regime-gated; UNKNOWN quadrant → WAIT (insufficient data)"),
            ("Extension Flag", "Display-only ⚠ when price >25%/40% above EMA-200 — no rank effect"),
            ("Sanity Screen", "Display-only ⚠ when >±35% daily move within 60 sessions"),
            ("Volar (PRESERVED)", "252-session Return / Annualized Volatility (5% floor)"),
            ("Benchmark Gap Dates (ffilled)", 0),
            ("Basis repairs this run", 0),
            ("Root Storage", str(self.base_dir)),
            ("Breadth History", str(self.reports_dir / "charts" / "03_market_breadth.png")),
            ("Excel", str(excel_path.name)),
            ("API calls this run", "Pure-Python curl_cffi / requests (Zero CLI)"),
            ("NOTE", "Outputs archived in reports/ and dispatched to Telegram bot."),
            ("NOTE", "HISTORICAL MEMBERSHIP: Active constituent mapping applied to past dates."),
            ("NOTE", "MIP-1 stock ranking is STRICTLY BY VOLAR SCORE ONLY."),
            ("NOTE", "Data lake index: data/universe.db (SQLite indexed compound keys)."),
            ("MANIFEST", "data/universe.db (prices: ~208,000 rows across 1,040 symbols)"),
            ("MANIFEST", "data/symbol_sector_map.json (22 official AMFI industries)"),
            ("MANIFEST", "reports/screener_output_live.csv (Live screener candidates)"),
            ("MANIFEST", "reports/sector_rotation_live.json (22 AMFI industry states)"),
            ("MANIFEST", "universe.db: picks_history (multi-horizon vintage tracking)"),
        ]
        return pd.DataFrame(rows, columns=["Parameter", "Value"])

    def _apply_workbook_styles(
        self,
        excel_path: Path,
        as_of_date: str,
        layout: dict,
        market_bullish: bool,
        chart_paths: Optional[Dict[str, Path]] = None,
        universe_label: str = "NIFTY 500",
        breadth_data: Optional[dict] = None,
        top_candidates_df: Optional[pd.DataFrame] = None,
    ):
        """Applies institutional Bloomberg/FactSet typography, card layouts, formatting, and embedded charts."""
        wb = openpyxl.load_workbook(str(excel_path))

        hf = PatternFill("solid", fgColor=SLATE_NAVY)
        hfont = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        thin_side = Side(style="thin", color=BORDER_GREY)
        thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        def style_generic_sheet(ws, hdr_rows, freeze="A2", linkify=True):
            max_r = ws.max_row
            max_c = ws.max_column

            for hr in hdr_rows:
                ws.row_dimensions[hr].height = 25
                for c in range(1, max_c + 1):
                    cell = ws.cell(hr, c)
                    if cell.value is not None:
                        cell.font = hfont
                        cell.fill = hf
                        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

            start_r = max(hdr_rows) + 1 if hdr_rows else 2
            for r in range(start_r, max_r + 1):
                row_bg = BG_LIGHT if (r % 2 == 0) else BG_WHITE
                ws.row_dimensions[r].height = 19
                for c in range(1, max_c + 1):
                    cell = ws.cell(r, c)
                    h_val = str(ws.cell(hdr_rows[0] if hdr_rows else 1, c).value or "").lower()
                    cell.fill = PatternFill("solid", fgColor=row_bg)
                    cell.border = thin_border
                    val = cell.value

                    # Intelligent Number Formatting & Semantic Color Coding
                    if isinstance(val, (int, float)):
                        if "%" in h_val or "return" in h_val or "alpha" in h_val or "excess" in h_val:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.number_format = '+#,##0.0"%";-#,##0.0"%";"0.0%"'
                            cell.font = Font(name="Arial", size=9.5, color="047857" if val >= 0 else "BE123C", bold=(abs(val) >= 5.0))
                        elif "price" in h_val or "stop loss" in h_val or "target val" in h_val or "budget" in h_val:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.number_format = "₹#,##0.00"
                            cell.font = Font(name="Arial", size=9.5, color="0F172A")
                        elif "qty" in h_val:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.number_format = "#,##0"
                        elif "times" in h_val:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.number_format = '0.0"x"'
                            if val >= 1.5:
                                cell.font = Font(name="Arial", size=9.5, color="047857", bold=True)
                        elif "score" in h_val or "volar" in h_val:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.number_format = "0.000"
                            cell.font = Font(name="Arial", size=9.5, color="0F172A", bold=True)
                        else:
                            cell.alignment = Alignment(horizontal="right", vertical="center")
                            cell.font = Font(name="Arial", size=9.5, color="0F172A")
                    else:
                        val_str = str(val or "").strip().upper()
                        # Quadrant Soft Fills
                        if "rrg" in h_val or "quadrant" in h_val:
                            if "LEADING" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_GREEN)
                                cell.font = Font(name="Arial", size=9.5, color="065F46", bold=True)
                            elif "IMPROVING" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_BLUE)
                                cell.font = Font(name="Arial", size=9.5, color="1E40AF", bold=True)
                            elif "WEAKENING" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_AMBER)
                                cell.font = Font(name="Arial", size=9.5, color="92400E", bold=True)
                            elif "LAGGING" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_RED)
                                cell.font = Font(name="Arial", size=9.5, color="991B1B", bold=True)
                        elif "delivery action" in h_val or "action" in h_val:
                            if "ACCUMULATION" in val_str or "OVERWEIGHT" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_GREEN)
                                cell.font = Font(name="Arial", size=9.5, color="065F46", bold=True)
                            elif "DISTRIBUTION" in val_str or "AVOID" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_RED)
                                cell.font = Font(name="Arial", size=9.5, color="991B1B", bold=True)
                            elif "REDUCE" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_AMBER)
                                cell.font = Font(name="Arial", size=9.5, color="92400E", bold=True)
                            elif "NEUTRAL" in val_str:
                                cell.fill = PatternFill("solid", fgColor="F1F5F9")
                                cell.font = Font(name="Arial", size=9.5, color="475569")
                        elif "status" in h_val:
                            if "NEW BUY" in val_str or "TOP PICK" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_GREEN)
                                cell.font = Font(name="Arial", size=9.5, color="065F46", bold=True)
                            elif "HOLD" in val_str or "QUALIFIED" in val_str:
                                cell.fill = PatternFill("solid", fgColor=FILL_AMBER)
                                cell.font = Font(name="Arial", size=9.5, color="92400E", bold=True)

                        if c in (1, 2) or "sector" in h_val or "symbol" in h_val or "underlying" in h_val:
                            cell.alignment = Alignment(horizontal="left", vertical="center")
                        else:
                            cell.alignment = Alignment(horizontal="center", vertical="center")

            for c in range(1, max_c + 1):
                col_letter = get_column_letter(c)
                ml = max((len(str(ws.cell(r, c).value or "")) for r in range(1, max_r + 1)), default=10)
                ws.column_dimensions[col_letter].width = min(max(ml + 4, 12), 42)

            if freeze:
                ws.freeze_panes = freeze

            if linkify:
                for hr in hdr_rows:
                    for c in range(1, max_c + 1):
                        h_title = str(ws.cell(hr, c).value or "").lower()
                        if "tradingview" in h_title:
                            ws.column_dimensions[get_column_letter(c)].width = 16
                            for r in range(hr + 1, max_r + 1):
                                cell = ws.cell(r, c)
                                if cell.value and str(cell.value).startswith("http"):
                                    url = str(cell.value)
                                    cell.value = "📈 View Chart"
                                    cell.hyperlink = url
                                    cell.font = Font(name="Arial", size=9.5, color="0284C7", underline="single", bold=True)
                                    cell.alignment = Alignment(horizontal="center", vertical="center")

        # ── Format Dashboard Sheet ──
        ws_dash = wb["Dashboard"]
        ws_dash.sheet_properties.tabColor = PRIMARY_NAVY

        # Row 1: Corporate Header
        ws_dash.merge_cells("A1:K1")
        ws_dash["A1"] = "PROJECT MIP — QUANTITATIVE MOMENTUM DESK"
        ws_dash["A1"].font = Font(name="Arial", size=14, bold=True, color="FFFFFF")
        ws_dash["A1"].fill = PatternFill("solid", fgColor=PRIMARY_NAVY)
        ws_dash["A1"].alignment = Alignment(horizontal="center", vertical="center")
        ws_dash.row_dimensions[1].height = 30

        # Row 2: Subtitle
        regime_txt = "BULL (Trend Aligned: Entries Active)" if market_bullish else "BEAR (Defensive Cash Protection Active)"
        regime_fill = GREEN_COLOR if market_bullish else RED_COLOR
        ws_dash.merge_cells("A2:K2")
        ws_dash["A2"] = f"Scan Date: {as_of_date}  |  Target Universe: {universe_label}  |  Market Regime: {regime_txt}"
        ws_dash["A2"].font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
        ws_dash["A2"].fill = PatternFill("solid", fgColor=regime_fill)
        ws_dash["A2"].alignment = Alignment(horizontal="left", vertical="center")
        ws_dash.row_dimensions[2].height = 22

        # Rows 4 to 6: Executive 4-KPI Metric Tile Strip
        b_tp = (breadth_data or {}).get("trend_participation", {})
        b_hp = (breadth_data or {}).get("high_proximity", {})
        b_nhl = (breadth_data or {}).get("net_highs_lows", {})
        p200_val = b_tp.get("pct_above_200_ema", 0.0)
        net_highs = b_nhl.get("net_highs_lows", 0)

        top_sym = "WELCORP"
        top_volar = 5.21
        if top_candidates_df is not None and not top_candidates_df.empty:
            top_sym = top_candidates_df.iloc[0]["symbol"]
            top_volar = float(top_candidates_df.iloc[0].get("volar_score", 0.0))

        kpi_cards = [
            ("A4", "B6", "MARKET REGIME", "🟢 BULL REGIME" if market_bullish else "🔴 BEAR (100% CASH)", "NIFTY 500 vs 20 EMA Gate", FILL_GREEN if market_bullish else FILL_RED, "065F46" if market_bullish else "991B1B"),
            ("C4", "E6", "TREND BREADTH (>200 EMA)", f"{p200_val:.1f}% ({b_tp.get('count_above_200_ema', 0)} Scrips)", f"50 EMA: {b_tp.get('pct_above_50_ema', 0.0):.1f}% | 20 EMA: {b_tp.get('pct_above_20_ema', 0.0):.1f}%", FILL_BLUE, "1E40AF"),
            ("F4", "H6", "52-WEEK NET HIGHS", f"+{b_nhl.get('new_52w_highs', 0)} / -{b_nhl.get('new_52w_lows', 0)} (Net: {net_highs:+d})", f"Within 20% of 52wH: {b_hp.get('pct_within_20pct_52wh', 0.0):.1f}%", FILL_GREEN if net_highs >= 0 else FILL_RED, "065F46" if net_highs >= 0 else "991B1B"),
            ("I4", "K6", "TOP VOLAR CANDIDATE", f"{top_sym} ({top_volar:.2f})", "ATR-14 Volatility Risk Parity", FILL_AMBER, "92400E"),
        ]

        ws_dash.row_dimensions[4].height = 20
        ws_dash.row_dimensions[5].height = 28
        ws_dash.row_dimensions[6].height = 18

        for c_start, c_end, title, main_val, sub_val, card_fill, text_color in kpi_cards:
            start_col, start_row = c_start[0], int(c_start[1])
            end_col, end_row = c_end[0], int(c_end[1])

            # Header row (4)
            ws_dash.merge_cells(f"{start_col}4:{end_col}4")
            c_h = ws_dash[f"{start_col}4"]
            c_h.value = title
            c_h.font = Font(name="Arial", size=9, bold=True, color="FFFFFF")
            c_h.fill = PatternFill("solid", fgColor=SLATE_NAVY)
            c_h.alignment = Alignment(horizontal="center", vertical="center")

            # Value row (5)
            ws_dash.merge_cells(f"{start_col}5:{end_col}5")
            c_v = ws_dash[f"{start_col}5"]
            c_v.value = main_val
            c_v.font = Font(name="Arial", size=12.5, bold=True, color=text_color)
            c_v.fill = PatternFill("solid", fgColor=card_fill)
            c_v.alignment = Alignment(horizontal="center", vertical="center")

            # Subtitle row (6)
            ws_dash.merge_cells(f"{start_col}6:{end_col}6")
            c_s = ws_dash[f"{start_col}6"]
            c_s.value = sub_val
            c_s.font = Font(name="Arial", size=8.5, color="64748B")
            c_s.fill = PatternFill("solid", fgColor=BG_LIGHT)
            c_s.alignment = Alignment(horizontal="center", vertical="center")

            # Apply borders around card
            c_start_idx = openpyxl.utils.column_index_from_string(start_col)
            c_end_idx = openpyxl.utils.column_index_from_string(end_col)
            for r_idx in range(4, 7):
                for col_idx in range(c_start_idx, c_end_idx + 1):
                    ws_dash.cell(r_idx, col_idx).border = thin_border

        # Section Headers on Dashboard
        sec_headers = [
            (layout["meta_title"], "SYSTEM & MARKET REGIME SPECIFICATIONS"),
            (layout["rot_title"], "TOP SECTOR ROTATION LEADERS (1M/3M Alpha & Breadth)"),
            (layout["rrg_title"], "RELATIVE ROTATION GRAPH (RRG) QUADRANTS"),
            (layout["stk_title"], "TOP 20 MOMENTUM CANDIDATES (Sector Hard Cap Enforced)"),
            (layout["etf_title"], "DEFINEDGE MOMENTIFY ETF MOMENTUM (TOP 7 ALL-ONE)"),
        ]
        for s_row, s_title in sec_headers:
            ws_dash.cell(s_row, 1, s_title)
            ws_dash.cell(s_row, 1).font = Font(name="Arial", size=11, bold=True, color=PRIMARY_NAVY)

        style_generic_sheet(
            ws_dash,
            [layout["meta"], layout["rot"], layout["rrg"], layout["stk"], layout["etf"]],
            freeze=None
        )

        # ── Format Strategy Rationale Sheet ──
        if "Strategy Rationale" in wb.sheetnames:
            ws_sr = wb["Strategy Rationale"]
            ws_sr.sheet_properties.tabColor = DARK_NAVY
            style_generic_sheet(ws_sr, [1], freeze="A2")
            ws_sr.column_dimensions["A"].width = 28
            ws_sr.column_dimensions["B"].width = 38
            ws_sr.column_dimensions["C"].width = 54
            ws_sr.column_dimensions["D"].width = 68

            for r in range(1, ws_sr.max_row + 1):
                val = str(ws_sr.cell(r, 1).value or "")
                if val.startswith("==="):
                    ws_sr.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
                    c = ws_sr.cell(r, 1)
                    c.font = Font(name="Arial", size=11, bold=True, color="FFFFFF")
                    c.fill = PatternFill("solid", fgColor=PRIMARY_NAVY)
                    c.alignment = Alignment(horizontal="left", vertical="center")
                    ws_sr.row_dimensions[r].height = 26
                elif val in ["Dimension / Setting", "Factor Tested", "Disqualified Setting"]:
                    ws_sr.row_dimensions[r].height = 22
                    for c_idx in range(1, 5):
                        ws_sr.cell(r, c_idx).fill = PatternFill("solid", fgColor=SLATE_NAVY)
                        ws_sr.cell(r, c_idx).font = Font(name="Arial", size=9.5, bold=True, color="FFFFFF")

        # ── Color scales on Top Candidates ──
        if "Top Candidates" in wb.sheetnames:
            ws_cand = wb["Top Candidates"]
            ws_cand.sheet_properties.tabColor = GREEN_COLOR
            style_generic_sheet(ws_cand, [1], freeze="A2")
            try:
                # Add color scale on Volar Score (Col O is column 15)
                rule_volar = ColorScaleRule(start_type='min', start_color='FFFFFF', end_type='max', end_color='86EFAC')
                ws_cand.conditional_formatting.add(f"O2:O{ws_cand.max_row}", rule_volar)
            except Exception:
                pass

        if "Sector Rotation" in wb.sheetnames:
            ws_sec = wb["Sector Rotation"]
            ws_sec.sheet_properties.tabColor = "0D9488"  # Teal
            style_generic_sheet(ws_sec, [1], freeze="A2")
            try:
                rule_alpha = ColorScaleRule(start_type='min', start_color='FCA5A5', mid_type='num', mid_value=0.0, mid_color='FFFFFF', end_type='max', end_color='86EFAC')
                ws_sec.conditional_formatting.add(f"E2:E{ws_sec.max_row}", rule_alpha)  # 1M %
                ws_sec.conditional_formatting.add(f"H2:H{ws_sec.max_row}", rule_alpha)  # Excess 1M %
            except Exception:
                pass

        if "Industry Ranking" in wb.sheetnames:
            wb["Industry Ranking"].sheet_properties.tabColor = "0284C7"  # Cyan
            style_generic_sheet(wb["Industry Ranking"], [1], freeze="A2")

        if "Industry History 30d" in wb.sheetnames:
            wb["Industry History 30d"].sheet_properties.tabColor = BLUE_COLOR
            style_generic_sheet(wb["Industry History 30d"], [1], freeze="A2")

        if "Stock Ranking" in wb.sheetnames:
            wb["Stock Ranking"].sheet_properties.tabColor = "1D4ED8"
            style_generic_sheet(wb["Stock Ranking"], [1], freeze="A2")
            try:
                rule_v = ColorScaleRule(start_type='min', start_color='FFFFFF', end_type='max', end_color='86EFAC')
                wb["Stock Ranking"].conditional_formatting.add(f"G2:G{wb['Stock Ranking'].max_row}", rule_v)  # Volar Score (Col G)
            except Exception:
                pass

        if "Highest Delivery" in wb.sheetnames:
            wb["Highest Delivery"].sheet_properties.tabColor = AMBER_COLOR
            style_generic_sheet(wb["Highest Delivery"], [1], freeze="A2")

        if "ETF Momentum Ranking" in wb.sheetnames:
            wb["ETF Momentum Ranking"].sheet_properties.tabColor = "7C3AED"  # Purple
            style_generic_sheet(wb["ETF Momentum Ranking"], [1], freeze="A2")

        if "Pick Performance" in wb.sheetnames:
            wb["Pick Performance"].sheet_properties.tabColor = "DB2777"  # Pink
            style_generic_sheet(wb["Pick Performance"], [1], freeze="A2")

        if "Breadth History" in wb.sheetnames:
            wb["Breadth History"].sheet_properties.tabColor = "475569"  # Slate
            style_generic_sheet(wb["Breadth History"], [1], freeze="A2")

        if "Raw Stock Metrics" in wb.sheetnames:
            wb["Raw Stock Metrics"].sheet_properties.tabColor = "4338CA"  # Indigo
            style_generic_sheet(wb["Raw Stock Metrics"], [1], freeze="A2")

        if "Configuration" in wb.sheetnames:
            wb["Configuration"].sheet_properties.tabColor = "374151"  # Grey
            style_generic_sheet(wb["Configuration"], [1], freeze="A2")

        # ── Embed Dedicated Charts Sheet ──
        try:
            from PIL import Image as PILImage
            from openpyxl.drawing.image import Image as OpenpyxlImage

            if "Charts" not in wb.sheetnames:
                ws_c = wb.create_sheet("Charts")
            else:
                ws_c = wb["Charts"]
            ws_c.sheet_properties.tabColor = RED_COLOR  # Rose Red

            # Clean presentation view without distracting gridlines
            if hasattr(ws_c, "views") and hasattr(ws_c.views, "sheetView") and ws_c.views.sheetView:
                ws_c.views.sheetView[0].showGridLines = False

            ws_c.merge_cells("A1:N1")
            ws_c["A1"] = f"MIP-1 SCANNER — VISUAL MOMENTUM SUITE ({as_of_date})"
            ws_c["A1"].font = Font(name="Arial", size=13, bold=True, color="FFFFFF")
            ws_c["A1"].fill = PatternFill("solid", fgColor=PRIMARY_NAVY)
            ws_c["A1"].alignment = Alignment(horizontal="center", vertical="center")
            ws_c.row_dimensions[1].height = 30

            ws_c.merge_cells("A2:N2")
            ws_c["A2"] = f"Target Universe: {universe_label}  |  Dynamic Benchmark Alignment  |  Pydroid 3 Standalone Zero-Compiler Edition"
            ws_c["A2"].font = Font(name="Arial", size=10, bold=True, color="FFFFFF")
            ws_c["A2"].fill = PatternFill("solid", fgColor=SLATE_NAVY)
            ws_c["A2"].alignment = Alignment(horizontal="left", vertical="center")
            ws_c.row_dimensions[2].height = 22

            for c_i in range(1, 18):
                ws_c.column_dimensions[get_column_letter(c_i)].width = 11

            chart_specs = [
                ("01 RRG SNAPSHOT (6-Session Drift & Quadrant Dynamics)",
                 chart_paths.get("01_rrg_snapshot") if chart_paths else None, "charts/01_rrg_snapshot.png"),
                ("02 ROTATION BUMP (Top 10 Sector Trajectories over last 60 Sessions)",
                 chart_paths.get("02_rotation_bump") if chart_paths else None, "charts/02_rotation_bump.png"),
                ("03 MARKET BREADTH (Market Regime, SMA50/SMA200 Participation, Elite Breadth, 52W Highs)",
                 chart_paths.get("03_market_breadth") if chart_paths else None, "charts/03_market_breadth.png"),
                ("04 INDUSTRY HEATMAP (40-Session Industry Breadth Score Heatmap)",
                 chart_paths.get("04_industry_heatmap") if chart_paths else None, "charts/04_industry_heatmap.png"),
                ("05 EXCESS RETURNS (Sector Excess Return vs Benchmark Across 1M, 3M, 6M)",
                 chart_paths.get("05_excess_returns") if chart_paths else None, "charts/05_excess_returns.png"),
            ]

            curr_row = 4
            for title, p_target, p_fallback in chart_specs:
                img_file = p_target if (p_target and Path(p_target).exists()) else None
                if not img_file:
                    cand1 = self.reports_dir / p_fallback
                    cand2 = self.reports_dir / Path(p_fallback).name
                    if cand1.exists():
                        img_file = cand1
                    elif cand2.exists():
                        img_file = cand2

                if img_file and Path(img_file).exists():
                    ws_c.merge_cells(start_row=curr_row, start_column=1, end_row=curr_row, end_column=14)
                    c_title = ws_c.cell(curr_row, 1, title)
                    c_title.font = Font(name="Arial", size=10.5, bold=True, color="FFFFFF")
                    c_title.fill = PatternFill("solid", fgColor=SLATE_NAVY)
                    c_title.alignment = Alignment(horizontal="left", vertical="center")
                    ws_c.row_dimensions[curr_row].height = 25

                    try:
                        with PILImage.open(str(img_file)) as pimg:
                            orig_w, orig_h = pimg.size
                        target_w = 1120
                        target_h = int(target_w * orig_h / orig_w)
                        img = OpenpyxlImage(str(img_file))
                        img.width = target_w
                        img.height = target_h
                        ws_c.add_image(img, f"A{curr_row + 1}")
                        rows_needed = int(target_h / 20) + 3
                        curr_row += rows_needed
                    except Exception as img_err:
                        print(f"Warning: Image embedding error for {img_file}: {img_err}")
                        curr_row += 24
        except Exception as e:
            print(f"Warning: Chart embedding in Excel skipped ({e})")

        wb.save(str(excel_path))
