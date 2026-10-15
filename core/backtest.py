"""
Project MIP Pydroid 3: Production Institutional Vector Backtest Engine
Directive: DIR-PROD-PYDROID3-PORT-01 (Standing Institutional Audit Parity)

High-performance, zero-compiler backtest simulator running directly on SQLite universe data:
  - Strict t+1 execution at Open price (zero lookahead bias).
  - Whole-share integer execution (zero fractional shares).
  - Indian statutory friction schedule (STT, Exchange Turnover, GST, Stamp Duty, Brokerage) + Slippage.
  - Realistic delisting handling (liquidates at last available traded close / salvage value, never buy price).
  - Risk-free rate adjusted Sharpe (Rf = 6.5%) & Sortino ratios.
  - Native Monte Carlo random portfolio permutation support.
  - Generates comprehensive trade log CSV & backtest results JSON.
"""

import sys
import math
import json
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .data_engine import (
    get_base_dir,
    load_bars,
    load_trading_calendar,
    load_symbol_sector_map,
)
from .portfolio import PortfolioManager, normalize_sector


class LightweightBacktester:
    """Zero-compiler vectorized portfolio backtester for Pydroid 3."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.benchmark_csv = self.base_dir / "data" / "benchmark_nifty500.csv"
        self.pm = PortfolioManager(self.base_dir)
        self.sector_map = load_symbol_sector_map()
        try:
            from .analytical_price import AnalyticalPriceEngine
            self.analytical_engine = AnalyticalPriceEngine(self.base_dir / "data" / "corporate_actions_registry.json")
        except Exception:
            self.analytical_engine = None

    def log(self, msg: str):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [Backtest] {msg}")

    def load_benchmark(self) -> pd.DataFrame:
        if not self.benchmark_csv.exists():
            return pd.DataFrame(columns=["date", "close"])
        df = pd.read_csv(self.benchmark_csv)
        df["date"] = df["date"].astype(str)
        return df

    def run(
        self,
        start_date: str = "2016-01-01",
        end_date: str = "2026-08-31",
        top_n: int = 20,
        exit_buffer: Optional[int] = 40,
        use_regime_filter: bool = True,
        initial_capital: float = 1_000_000.0,
        friction_bps: float = 15.0,
        slippage_bps: float = 5.0,
        rf_rate: float = 0.065,
        random_selection: bool = False,
        seed: Optional[int] = None,
        rebalance_schedule: str = "month_end",
        max_per_sector: Optional[int] = 2,
        sizing_mode: Optional[str] = None,
        risk_per_trade_pct: Optional[float] = None,
        allow_research_overrides: bool = False,
    ) -> Dict:
        """
        Runs historical monthly rebalance backtest with t+1 Open execution,
        integer shares, statutory frictions, exit buffer, market regime filter,
        max_per_sector concentration hard cap, and configurable sizing mode.
        Defaults to production-authoritative 'atr_risk_parity'.
        """
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise ValueError(f"INVALID_CAPITAL: initial_capital must be a positive finite number, got {initial_capital}")

        from .settings import load_investing_settings
        st = load_investing_settings(self.base_dir)
        sizing_mode = str(sizing_mode if sizing_mode is not None else st.get("sizing_mode", "atr_risk_parity")).strip().lower()
        if sizing_mode not in ("atr_risk_parity", "equal_weight"):
            raise ValueError(f"INVALID_SIZING_MODE: '{sizing_mode}' is not supported. Must be 'atr_risk_parity' or 'equal_weight'.")

        risk_per_trade_pct = float(risk_per_trade_pct if risk_per_trade_pct is not None else st.get("risk_per_trade_pct", 1.0))
        if not math.isfinite(risk_per_trade_pct) or risk_per_trade_pct <= 0:
            raise ValueError(f"INVALID_RISK_PER_TRADE: risk_per_trade_pct must be a positive finite percentage, got {risk_per_trade_pct}")
        if abs(risk_per_trade_pct - 1.0) > 1e-6 and not allow_research_overrides:
            raise ValueError(
                f"PRODUCTION_RISK_OVERRIDE_REJECTED: Production execution strictly requires risk_per_trade_pct=1.0. "
                f"Resolved value is {risk_per_trade_pct}%. Research overrides require allow_research_overrides=True."
            )

        mode_str = f"Random Selection (Seed {seed})" if random_selection else "Volar Momentum Ranking"
        self.log(f"Running backtest {start_date} to {end_date} (Top {top_n}, Mode: {mode_str}, Max/Sector: {max_per_sector}, Sizing: {sizing_mode})...")

        # 1. Warmup lookback for 252d indicators
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        warmup_dt = start_dt - datetime.timedelta(days=550)
        warmup_str = warmup_dt.strftime("%Y-%m-%d")

        self.log(f"Loading bars from SQLite ({warmup_str} to {end_date})...")
        bars = load_bars(start_date=warmup_str, end_date=end_date)
        bars["date"] = bars["date"].astype(str)
        bars = bars.sort_values(by=["symbol", "date"]).reset_index(drop=True)
        bars["sector"] = bars["symbol"].map(lambda s: self.sector_map.get(s, "OTHER"))

        # Point-in-time corporate action adjustments via AnalyticalPriceEngine (DEF-01)
        if getattr(self, "analytical_engine", None) and self.analytical_engine.actions_by_symbol:
            for ca_sym in self.analytical_engine.actions_by_symbol:
                mask = bars["symbol"] == ca_sym
                if mask.any():
                    df_sub = bars.loc[mask].copy()
                    df_adj, _ = self.analytical_engine.derive_analytical_series(
                        ca_sym, df_sub, as_of_date=end_date
                    )
                    if not df_adj.empty and len(df_adj) == len(df_sub):
                        for col in ["open", "high", "low", "close"]:
                            if col in df_adj.columns:
                                bars.loc[mask, col] = df_adj[col].values

        self.delisted_symbols = set(bars.loc[bars["is_delisted"] == 1, "symbol"].unique()) if "is_delisted" in bars.columns else set()

        b_df = self.load_benchmark()
        bench_bull_map = {}
        bench_close_map = {}
        if not b_df.empty:
            b_df["date"] = b_df["date"].astype(str)
            b_df = b_df.sort_values("date").reset_index(drop=True)
            from .benchmark_validator import validate_benchmark_dataframe, compute_benchmark_indicators
            valid, reason = validate_benchmark_dataframe(b_df, min_history=20)
            if valid:
                b_df = compute_benchmark_indicators(b_df)
                bench_bull_map = dict(zip(b_df["date"], b_df["close"] >= b_df["ema_20"]))
                bench_close_map = dict(zip(b_df["date"], b_df["close"]))
            else:
                self.log(f"Warning: Benchmark data invalid ({reason}). Backtester will operate fail-closed.")

        self.log("Computing momentum factors across universe...")
        bars["close_252d"] = bars.groupby("symbol")["close"].shift(252)
        bars["ret_1y"] = (bars["close"] / bars["close_252d"] - 1.0)
        bars["daily_ret"] = bars.groupby("symbol")["close"].pct_change()
        bars["vol_252"] = bars.groupby("symbol")["daily_ret"].transform(
            lambda s: s.rolling(252, min_periods=min(50, len(s))).std() * np.sqrt(252)
        )
        bars["volar"] = bars["ret_1y"] / bars["vol_252"].clip(lower=0.05)
        bars["ema_200"] = bars.groupby("symbol")["close"].transform(
            lambda s: s.ewm(span=200, adjust=True, min_periods=min(50, len(s))).mean()
        )
        bars["high_252"] = bars.groupby("symbol")["high"].transform(
            lambda s: s.rolling(252, min_periods=min(50, len(s))).max()
        )
        prev_close_bars = bars.groupby("symbol")["close"].shift(1)
        bars["tr"] = np.maximum(
            bars["high"] - bars["low"],
            np.maximum((bars["high"] - prev_close_bars).abs(), (bars["low"] - prev_close_bars).abs())
        )
        bars["atr_14"] = bars.groupby("symbol")["tr"].transform(
            lambda s: s.rolling(14, min_periods=min(5, len(s))).mean()
        ).fillna(bars["close"] * 0.03)

        # Filters (including Filter 3: RS vs Benchmark > 200 EMA of RS)
        bars["pass_retrace"] = bars["close"] >= 0.80 * bars["high_252"]
        bars["pass_trend"] = bars["close"] > bars["ema_200"]
        if bench_close_map:
            bars["bench_close"] = bars["date"].map(bench_close_map)
            valid_bench = bars["bench_close"].notna() & (bars["bench_close"] > 0)
            bars["rs_ratio"] = np.where(valid_bench, bars["close"] / bars["bench_close"], np.nan)
            bars["rs_ema_200"] = bars.groupby("symbol")["rs_ratio"].transform(
                lambda s: s.ewm(span=200, adjust=True, min_periods=min(50, len(s))).mean()
            )
            bars["pass_rs"] = (valid_bench & (bars["rs_ratio"] > bars["rs_ema_200"])).fillna(False)
        else:
            bars["pass_rs"] = False if use_regime_filter else True

        bars["pass_all"] = bars["pass_retrace"] & bars["pass_trend"] & bars["pass_rs"] & (bars["volar"] > 0)

        # Build chronological calendar mapping
        all_dates = sorted(bars["date"].unique())
        date_to_idx = {d: i for i, d in enumerate(all_dates)}

        # Identify monthly rebalance signal dates
        test_dates = [d for d in all_dates if d >= start_date]
        df_dates = pd.DataFrame({"date": test_dates})
        df_dates["month"] = df_dates["date"].str[:7]
        if rebalance_schedule == "month_start":
            rebalance_signal_dates = df_dates.groupby("month")["date"].first().tolist()
        else:
            rebalance_signal_dates = df_dates.groupby("month")["date"].last().tolist()

        if len(rebalance_signal_dates) < 2:
            return {"error": "Insufficient rebalance dates in range"}

        self.log(f"Pre-indexing snapshots across {len(rebalance_signal_dates)} monthly rebalances...")
        # Index slices for signal evaluation and execution
        bars_by_date = {d: g for d, g in bars[bars["date"].isin(set(all_dates))].groupby("date")}

        # Fast price lookups per date: date -> {sym: open}, date -> {sym: close}, date -> {sym: atr_14}
        open_by_date = {}
        close_by_date = {}
        atr_by_date = {}
        for d in all_dates:
            g = bars_by_date.get(d)
            if g is not None:
                open_by_date[d] = dict(zip(g["symbol"], g["open"]))
                close_by_date[d] = dict(zip(g["symbol"], g["close"]))
                atr_by_date[d] = dict(zip(g["symbol"], g["atr_14"]))

        # State tracking
        cash = initial_capital
        current_holdings = {}  # {sym: {"shares": int, "buy_px": float, "cost_basis": float, "entry_date": str}}
        last_known_close = {}  # {sym: last_seen_close_px}

        portfolio_equity = [(rebalance_signal_dates[0], initial_capital)]
        daily_equity = [(start_date, initial_capital)]
        closed_trades = []
        winning_trades = 0
        total_closed_trades = 0

        slippage_rate = slippage_bps / 10000.0

        for i in range(len(rebalance_signal_dates) - 1):
            signal_date = rebalance_signal_dates[i]
            next_signal_date = rebalance_signal_dates[i + 1]

            # Signal date index in all_dates
            sig_idx = date_to_idx.get(signal_date, -1)
            # t+1 execution date is next available session in calendar
            exec_idx = sig_idx + 1 if (sig_idx >= 0 and sig_idx + 1 < len(all_dates)) else sig_idx
            exec_date = all_dates[exec_idx]

            # Update last known closes up to exec_date
            c_slice = close_by_date.get(signal_date, {})
            last_known_close.update(c_slice)
            o_slice = open_by_date.get(exec_date, {})
            c_exec = close_by_date.get(exec_date, {})
            last_known_close.update(c_exec)

            # 1. EVALUATE EXITS FOR CURRENT HOLDINGS (Rank 40 Exit Buffer & Trend Rules)
            retained_holdings = {}
            if current_holdings:
                sig_slice = bars_by_date.get(signal_date, pd.DataFrame())
                rank_map = {}
                sym_metrics = {}
                if not sig_slice.empty:
                    q_cands = sig_slice[sig_slice["pass_all"]].sort_values(by="volar", ascending=False)
                    rank_map = {sym: r + 1 for r, sym in enumerate(q_cands["symbol"].tolist())}
                    for _, row in sig_slice.iterrows():
                        sym_metrics[row["symbol"]] = {
                            "close": row["close"],
                            "high_252": row.get("high_252", row["close"]),
                            "ema_200": row.get("ema_200", row["close"]),
                        }

                effective_buffer = exit_buffer if exit_buffer is not None else (top_n * 2)

                # Adjust active holdings for splits/bonuses between rebalance dates (DEF-01)
                if getattr(self, "analytical_engine", None):
                    for sym, h in current_holdings.items():
                        active_actions = self.analytical_engine.get_active_actions(sym, signal_date)
                        last_ca_date = h.get("last_ca_date", h["entry_date"])
                        for a in active_actions:
                            if last_ca_date < a.ex_date <= signal_date:
                                factor = a.adjustment_factor
                                if factor > 0 and factor != 1.0:
                                    h["shares"] = int(round(h["shares"] / factor))
                                    h["buy_px"] = round(h["buy_px"] * factor, 2)
                                    h["last_ca_date"] = a.ex_date

                for sym, h in current_holdings.items():
                    shares = h["shares"]
                    buy_px = h["buy_px"]
                    entry_dt = h["entry_date"]
                    cost_basis = h["cost_basis"]

                    m = sym_metrics.get(sym)
                    rank = rank_map.get(sym, 999999)

                    exit_reason = None
                    if m is None or m["close"] <= 0:
                        exit_reason = "NO_DATA"
                    elif m["close"] < 0.80 * m["high_252"]:
                        exit_reason = "STOP_52W_HIGH_RETRACEMENT"
                    elif m["close"] < m["ema_200"]:
                        exit_reason = "STOP_200_EMA_BREAK"
                    elif rank > effective_buffer:
                        exit_reason = f"DROPOUT_RANK_{rank}"

                    if exit_reason is None and not random_selection:
                        # Retain position across rebalance (No needless liquidation!)
                        retained_holdings[sym] = h
                    else:
                        # Liquidate at exec_date Open
                        exit_px = o_slice.get(sym) or c_exec.get(sym) or last_known_close.get(sym, 0.0)
                        if exit_px <= 0:
                            exit_px = 0.0

                        # Distress liquidation haircut for delisted / suspended companies (DEF-07)
                        if sym in getattr(self, "delisted_symbols", set()) and (m is None or sym not in o_slice):
                            exit_px = exit_px * 0.50

                        gross_proceeds = shares * exit_px
                        sell_fric = self.pm.compute_frictions(gross_proceeds)["total_friction"] + (gross_proceeds * slippage_rate)
                        net_proceeds = max(0.0, gross_proceeds - sell_fric)

                        cash += net_proceeds
                        total_closed_trades += 1
                        net_pnl = net_proceeds - cost_basis
                        ret_pct = round((net_proceeds / cost_basis - 1.0) * 100.0, 2) if cost_basis > 0 else -100.0

                        if net_pnl > 0:
                            winning_trades += 1

                        closed_trades.append({
                            "trade_id": total_closed_trades,
                            "symbol": sym,
                            "entry_date": entry_dt,
                            "entry_price": buy_px,
                            "exit_date": exec_date,
                            "exit_price": exit_px,
                            "shares": shares,
                            "gross_pnl": round(gross_proceeds - (shares * buy_px), 2),
                            "net_pnl": round(net_pnl, 2),
                            "return_pct": ret_pct,
                            "exit_reason": exit_reason or "REBALANCE",
                        })

                current_holdings = retained_holdings

            # 2. SELECT NEW ENTRANTS FOR OPEN SLOTS (Subject to Market Regime Filter)
            open_slots = top_n - len(current_holdings)
            sig_slice = bars_by_date.get(signal_date, pd.DataFrame())
            selected_symbols = []
            is_bull = bench_bull_map.get(signal_date, False) if use_regime_filter else True

            sector_counts = {}
            for sym in current_holdings:
                raw_sec = self.sector_map.get(sym, "OTHER")
                sec = normalize_sector(raw_sec)
                sector_counts[sec] = sector_counts.get(sec, 0) + 1

            if open_slots > 0 and is_bull and not sig_slice.empty:
                candidates = sig_slice[sig_slice["pass_all"]].copy()
                candidates = candidates[~candidates["symbol"].isin(set(current_holdings.keys()))]
                if random_selection:
                    rnd_seed = (seed + i) if seed is not None else None
                    if rnd_seed is not None:
                        np.random.seed(rnd_seed)
                    selected_symbols = candidates["symbol"].sample(n=min(open_slots, len(candidates)), random_state=rnd_seed).tolist()
                else:
                    sort_cols = ["volar"]
                    sort_asc = [False]
                    if "ret_1y" in candidates.columns:
                        sort_cols.append("ret_1y")
                        sort_asc.append(False)
                    sort_cols.append("symbol")
                    sort_asc.append(True)
                    candidates = candidates.sort_values(by=sort_cols, ascending=sort_asc)
                    if max_per_sector is not None:
                        for _, cand_row in candidates.iterrows():
                            sym = str(cand_row["symbol"]).strip().upper()
                            raw_sec = cand_row.get("sector") if "sector" in cand_row and pd.notna(cand_row["sector"]) else self.sector_map.get(sym, "OTHER")
                            sec = normalize_sector(raw_sec)
                            if sector_counts.get(sec, 0) < max_per_sector:
                                selected_symbols.append(sym)
                                sector_counts[sec] = sector_counts.get(sec, 0) + 1
                            if len(selected_symbols) >= open_slots:
                                break
                    else:
                        selected_symbols = candidates["symbol"].head(open_slots).tolist()

            # 3. ENTER NEW POSITIONS ON t+1 OPEN WITH WHOLE SHARES
            if selected_symbols and cash > 1000.0:
                investable_cash = cash * 0.99
                a_slice = atr_by_date.get(signal_date, {})

                if sizing_mode == "atr_risk_parity":
                    # Mark-to-market current portfolio capital
                    curr_invested = sum(
                        h["shares"] * (c_slice.get(sym) or last_known_close.get(sym, h["buy_px"]))
                        for sym, h in current_holdings.items()
                    )
                    curr_capital = cash + curr_invested
                    risk_budget = curr_capital * (risk_per_trade_pct / 100.0)

                    raw_entries = []
                    for sym in selected_symbols:
                        buy_px = o_slice.get(sym) or c_exec.get(sym, 0.0)
                        if buy_px <= 0:
                            continue
                        atr = a_slice.get(sym, buy_px * 0.03)
                        if not np.isfinite(atr) or atr <= 0:
                            atr = buy_px * 0.03
                        rps = max(2.0 * atr, buy_px * 0.02)
                        q_risk = int(risk_budget // rps) if rps > 0 else 0
                        q_cap = int((curr_capital * 0.25) // buy_px) if buy_px > 0 else 0
                        q_target = max(0, min(q_risk, q_cap))
                        if q_target > 0:
                            trade_val = q_target * buy_px
                            buy_fric = self.pm.compute_frictions(trade_val)["total_friction"] + (trade_val * slippage_rate)
                            raw_entries.append({
                                "symbol": sym,
                                "buy_px": buy_px,
                                "q_target": q_target,
                                "est_cost": trade_val + buy_fric,
                            })

                    total_req = sum(e["est_cost"] for e in raw_entries)
                    scale = (investable_cash / total_req) if (total_req > investable_cash and total_req > 0) else 1.0

                    for e in raw_entries:
                        sym = e["symbol"]
                        buy_px = e["buy_px"]
                        shares = int(e["q_target"] * scale)
                        if shares > 0:
                            trade_val = shares * buy_px
                            buy_fric = self.pm.compute_frictions(trade_val)["total_friction"] + (trade_val * slippage_rate)
                            total_cost = trade_val + buy_fric
                            if total_cost <= cash:
                                cash -= total_cost
                                current_holdings[sym] = {
                                    "shares": shares,
                                    "buy_px": buy_px,
                                    "cost_basis": total_cost,
                                    "entry_date": exec_date,
                                }
                else:
                    target_alloc = investable_cash / len(selected_symbols)
                    for sym in selected_symbols:
                        buy_px = o_slice.get(sym) or c_exec.get(sym, 0.0)
                        if buy_px > 0:
                            shares = int(target_alloc // buy_px)
                            if shares > 0:
                                trade_val = shares * buy_px
                                buy_fric = self.pm.compute_frictions(trade_val)["total_friction"] + (trade_val * slippage_rate)
                                total_cost = trade_val + buy_fric
                                if total_cost <= cash:
                                    cash -= total_cost
                                    current_holdings[sym] = {
                                        "shares": shares,
                                        "buy_px": buy_px,
                                        "cost_basis": total_cost,
                                        "entry_date": exec_date,
                                    }

            # Daily Equity Tracking between exec_date and next_signal_date
            sub_dates = [d for d in all_dates if exec_date <= d <= next_signal_date]
            for d in sub_dates:
                c_d = close_by_date.get(d, {})
                last_known_close.update(c_d)
                d_invested = sum(h["shares"] * (c_d.get(sym) or last_known_close.get(sym, 0.0)) for sym, h in current_holdings.items())
                daily_equity.append((d, round(cash + d_invested, 2)))

            # 4. MARK-TO-MARKET PORTFOLIO EQUITY AT NEXT SIGNAL DATE CLOSE
            c_next_sig = close_by_date.get(next_signal_date, {})
            last_known_close.update(c_next_sig)

            invested_val = 0.0
            for sym, h in current_holdings.items():
                m_px = c_next_sig.get(sym) or last_known_close.get(sym, 0.0)
                invested_val += h["shares"] * m_px

            total_equity = round(cash + invested_val, 2)
            portfolio_equity.append((next_signal_date, total_equity))

        # Final reconciliation: mark open positions at end of backtest
        final_equity = portfolio_equity[-1][1]

        # Performance analytics
        eq_df = pd.DataFrame(portfolio_equity, columns=["date", "equity"])
        eq_df["ret"] = eq_df["equity"].pct_change().fillna(0.0)

        total_return = (final_equity / initial_capital) - 1.0
        n_years = max(1.0, (datetime.datetime.strptime(end_date, "%Y-%m-%d") - start_dt).days / 365.25)
        cagr = ((final_equity / initial_capital) ** (1.0 / n_years) - 1.0) * 100.0

        # Drawdown
        eq_df["peak"] = eq_df["equity"].cummax()
        eq_df["drawdown"] = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"]
        max_dd = float(eq_df["drawdown"].min()) * 100.0

        # Daily Drawdown
        daily_df = pd.DataFrame(daily_equity, columns=["date", "equity"]).drop_duplicates(subset=["date"], keep="last")
        daily_df["peak"] = daily_df["equity"].cummax()
        daily_df["drawdown"] = (daily_df["equity"] - daily_df["peak"]) / daily_df["peak"]
        daily_max_dd = float(daily_df["drawdown"].min()) * 100.0
        daily_dd_min_idx = daily_df["drawdown"].idxmin()
        daily_max_dd_date = str(daily_df.loc[daily_dd_min_idx, "date"]) if pd.notna(daily_dd_min_idx) else ""

        # Recovery duration
        peak_val = float(daily_df.loc[daily_dd_min_idx, "peak"])
        post_dd = daily_df.loc[daily_dd_min_idx:]
        recovered = post_dd[post_dd["equity"] >= peak_val]
        if not recovered.empty:
            rec_date = str(recovered.iloc[0]["date"])
            rec_days = (datetime.datetime.strptime(rec_date, "%Y-%m-%d") - datetime.datetime.strptime(daily_max_dd_date, "%Y-%m-%d")).days
        else:
            rec_days = None

        # Annualized Sharpe & Sortino with Risk-Free Rate Rf = 6.5%
        ann_mean = float(eq_df["ret"].mean()) * 12.0
        ann_std = float(eq_df["ret"].std()) * np.sqrt(12.0)
        excess_mean = ann_mean - rf_rate

        sharpe = round(excess_mean / ann_std, 2) if ann_std > 0 else 0.0

        monthly_rf = rf_rate / 12.0
        downside_diff = eq_df[eq_df["ret"] < monthly_rf]["ret"] - monthly_rf
        downside_std = float(downside_diff.std()) * np.sqrt(12.0) if len(downside_diff) > 1 else ann_std
        sortino = round(excess_mean / downside_std, 2) if downside_std > 0 else 0.0

        calmar = round(cagr / abs(max_dd), 2) if abs(max_dd) > 0 else 0.0
        win_rate = round((winning_trades / max(1, total_closed_trades)) * 100.0, 1)

        # Benchmark comparison
        if not b_df.empty:
            b_start_rows = b_df[b_df["date"] >= start_date]
            b_start_px = float(b_start_rows.iloc[0]["close"]) if not b_start_rows.empty else float(b_df.iloc[0]["close"])
            b_end_rows = b_df[b_df["date"] <= end_date]
            b_end_px = float(b_end_rows.iloc[-1]["close"]) if not b_end_rows.empty else float(b_df.iloc[-1]["close"])

            if b_start_px > 0 and b_end_px > 0:
                bm_cagr = ((b_end_px / b_start_px) ** (1.0 / n_years) - 1.0) * 100.0
            else:
                bm_cagr = 0.0
        else:
            bm_cagr = 0.0

        results = {
            "start_date": start_date,
            "end_date": end_date,
            "years": round(n_years, 2),
            "initial_capital": initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100.0, 2),
            "cagr_pct": round(cagr, 2),
            "benchmark_cagr_pct": round(bm_cagr, 2),
            "excess_cagr_pct": round(cagr - bm_cagr, 2),
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "calmar_ratio": float(calmar),
            "max_drawdown_pct": round(max_dd, 2),
            "monthly_max_drawdown_pct": round(max_dd, 2),
            "daily_max_drawdown_pct": round(daily_max_dd, 2),
            "daily_max_drawdown_date": daily_max_dd_date,
            "drawdown_recovery_days": rec_days,
            "max_per_sector": max_per_sector,
            "sizing_mode": sizing_mode,
            "risk_per_trade_pct": risk_per_trade_pct,
            "is_production_contract": bool(abs(risk_per_trade_pct - 1.0) <= 1e-6 and sizing_mode == "atr_risk_parity" and max_per_sector == 2),
            "allow_research_overrides": bool(allow_research_overrides),
            "return_type": "price_appreciation_adjusted",
            "total_trades": total_closed_trades,
            "win_rate_pct": win_rate,
        }

        # Export trade log and results
        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        if closed_trades:
            trades_df = pd.DataFrame(closed_trades)
            trades_df.to_csv(reports_dir / "trade_log.csv", index=False)

        with open(reports_dir / "backtest_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        return results
