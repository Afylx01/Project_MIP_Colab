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
from typing import Any, Dict, List, Optional, Sequence, Tuple
import pandas as pd
import numpy as np

from .data_engine import (
    get_base_dir,
    load_bars,
    load_trading_calendar,
    load_symbol_sector_map,
)
from .portfolio import PortfolioManager, normalize_sector
from .universe_policy import (
    MIN_ELIGIBLE_SYMBOLS,
    check_breadth,
    min_pit_eligible,
    resolve_universe,
)


class LightweightBacktester:
    """Zero-compiler vectorized portfolio backtester for Pydroid 3."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        benchmark: str = "NIFTY500",
        output_dir: Optional[Path] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.benchmark_name = benchmark or "NIFTY500"
        self.benchmark_csv = self.base_dir / "data" / "benchmark_nifty500.csv"
        self.output_dir = Path(output_dir) if output_dir else (self.base_dir / "reports")
        self.pm = PortfolioManager(self.base_dir)
        self.sector_map = load_symbol_sector_map()
        try:
            from .analytical_price import AnalyticalPriceEngine
            self.analytical_engine = AnalyticalPriceEngine(self.base_dir / "data" / "corporate_actions_registry.json")
        except Exception:
            self.analytical_engine = None

    @staticmethod
    def build_trades_df(closed_trades: List[Dict[str, Any]], trade_cols: Optional[List[str]] = None) -> pd.DataFrame:
        """Constructs standardized DataFrame from closed trade records, normalizing legacy keys."""
        cols = trade_cols or [
            "trade_id", "symbol", "entry_date", "exit_date", "entry_px", "exit_px",
            "shares", "cost_basis", "net_proceeds", "net_pnl", "return_pct", "exit_reason"
        ]
        if not closed_trades:
            return pd.DataFrame(columns=cols)
        normalized = []
        for t in closed_trades:
            t_copy = dict(t)
            if "entry_px" not in t_copy and "entry_price" in t_copy:
                t_copy["entry_px"] = t_copy["entry_price"]
            if "exit_px" not in t_copy and "exit_price" in t_copy:
                t_copy["exit_px"] = t_copy["exit_price"]
            if "cost_basis" not in t_copy:
                t_copy["cost_basis"] = round(t_copy.get("shares", 0) * t_copy.get("entry_px", t_copy.get("entry_price", 0.0)), 2)
            if "net_proceeds" not in t_copy:
                t_copy["net_proceeds"] = round(t_copy.get("cost_basis", 0.0) + t_copy.get("net_pnl", 0.0), 2)
            normalized.append(t_copy)
        return pd.DataFrame(normalized, columns=cols)

    def log(self, msg: str):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [Backtest] {msg}")

    def load_benchmark(self, benchmark_override: Optional[str] = None) -> pd.DataFrame:
        try:
            from core.benchmark_validator import resolve_benchmark_dataframe
            bm_name = benchmark_override or getattr(self, "benchmark_name", "NIFTY500")
            return resolve_benchmark_dataframe(bm_name, base_dir=self.base_dir)
        except Exception:
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
        universe_mode: Optional[str] = None,
        explicit_symbols: Optional[Sequence[str]] = None,
        strict_point_in_time: bool = True,  # deprecated: historical index runs are always strict
        lookback_bars: int = 252,
        ema_trend_span: int = 200,
        retrace_threshold: float = 0.80,
    ) -> Dict:
        """
        Runs historical monthly rebalance backtest with t+1 Open execution,
        integer shares, statutory frictions, exit buffer, market regime filter,
        max_per_sector concentration hard cap, and configurable sizing mode.
        Defaults to production-authoritative 'atr_risk_parity'.

        universe_mode: "ALL" (full database cross-section) or a named index. A
        named index is resolved to point-in-time membership on each rebalance
        date. A named index without a PIT table, or a window with insufficient
        PIT breadth, is refused — there is no current-constituent fallback.
        strict_point_in_time is retained for API compatibility; historical
        index runs are always strict.
        """
        if not math.isfinite(initial_capital) or initial_capital <= 0:
            raise ValueError(f"INVALID_CAPITAL: initial_capital must be a positive finite number, got {initial_capital}")
        lookback_bars = int(lookback_bars)
        ema_trend_span = int(ema_trend_span)
        if lookback_bars < 60 or ema_trend_span < 20:
            raise ValueError("INVALID_FACTOR_WINDOW: lookback_bars>=60 and ema_trend_span>=20 required")
        if not (0.5 <= float(retrace_threshold) <= 1.0):
            raise ValueError("INVALID_RETRACE: retrace_threshold must be in [0.5, 1.0]")

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

        # Resolve the requested universe. ALL is the full database cross-section
        # (delisted names included). A named index is resolved from PIT snapshots;
        # there is no current-list fallback because that would be survivorship/
        # look-ahead biased. The live scanner is the only component allowed to use
        # the latest constituents.
        policy = resolve_universe(
            universe_mode, start_date, self.base_dir, explicit_symbols=explicit_symbols,
            end_date=end_date,
        )
        universe_label = str(policy["label"])
        universe_symbols: Optional[List[str]] = policy["symbols"]  # type: ignore[assignment]
        universe_source = str(policy["source"])
        pit_index = policy.get("pit_index")
        universe_point_in_time = bool(pit_index)
        survivorship_bias_risk = bool(policy["survivorship_bias_risk"])
        data_completeness_risk = bool(policy["data_completeness_risk"])
        if universe_symbols is not None:
            self.log(f"Using explicit research universe: {len(universe_symbols)} symbols.")
        else:
            self.log("Using ALL symbols (full delisted-inclusive cross-section).")

        mode_str = f"Random Selection (Seed {seed})" if random_selection else "Volar Momentum Ranking"
        self.log(f"Running backtest {start_date} to {end_date} (Top {top_n}, Mode: {mode_str}, Max/Sector: {max_per_sector}, Sizing: {sizing_mode}, Universe: {universe_label})...")

        # 1. Warmup lookback for 252d indicators
        start_dt = datetime.datetime.strptime(start_date, "%Y-%m-%d")
        warmup_dt = start_dt - datetime.timedelta(days=550)
        warmup_str = warmup_dt.strftime("%Y-%m-%d")
        cache_key = (
            warmup_str, end_date, getattr(self, "benchmark_name", "NIFTY500"),
            universe_label, tuple(universe_symbols) if universe_symbols else None,
            lookback_bars, ema_trend_span,
        )

        if getattr(self, "_prepared_cache_key", None) == cache_key and hasattr(self, "_prepared_cache"):
            c = self._prepared_cache
            bars_by_date = c["bars_by_date"]
            open_by_date = c["open_by_date"]
            close_by_date = c["close_by_date"]
            atr_by_date = c["atr_by_date"]
            all_dates = c["all_dates"]
            date_to_idx = c["date_to_idx"]
            self.delisted_symbols = c["delisted_symbols"]
            bench_bull_map = c["bench_bull_map"]
            b_df = c["b_df"]
            valid_dates_by_symbol = c.get("valid_dates_by_symbol", {})
            calendar_filtered_dates = c.get("calendar_filtered_dates", 0)
            universe_size = c.get("universe_size", 0)
            eligible_symbols = c.get("eligible_symbols", 0)
            if pit_index and eligible_symbols < MIN_ELIGIBLE_SYMBOLS:
                raise ValueError(
                    f"INSUFFICIENT_PIT_BREADTH: only {eligible_symbols} point-in-time members of "
                    f"'{pit_index}' have the required 252-bar history on {start_date}; minimum is "
                    f"{MIN_ELIGIBLE_SYMBOLS}."
                )
            check_breadth(eligible_symbols, universe_source)
        else:
            self.log(f"Loading bars from SQLite ({warmup_str} to {end_date})...")
            bars = load_bars(start_date=warmup_str, end_date=end_date, symbols=universe_symbols)
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

            # Resolve delisting from each symbol's last observed session rather than
            # trusting the per-row is_delisted flag (which is refreshed in bulk and can
            # flip for symbols that resume trading).
            last_bar_by_symbol = bars.groupby("symbol")["date"].max()
            self.delisted_symbols = set(last_bar_by_symbol[last_bar_by_symbol < end_date].index)
            if "is_delisted" in bars.columns:
                self.delisted_symbols |= set(
                    bars.loc[(bars["is_delisted"] == 1) & (bars["date"] == bars.groupby("symbol")["date"].transform("max")), "symbol"].unique()
                )

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
            bars["close_252d"] = bars.groupby("symbol")["close"].shift(lookback_bars)
            bars["ret_1y"] = (bars["close"] / bars["close_252d"] - 1.0)
            bars["daily_ret"] = bars.groupby("symbol")["close"].pct_change()
            bars["vol_252"] = bars.groupby("symbol")["daily_ret"].transform(
                lambda s: s.rolling(lookback_bars, min_periods=min(50, len(s))).std() * np.sqrt(252)
            )
            bars["volar"] = bars["ret_1y"] / bars["vol_252"].clip(lower=0.05)
            # Data-quality gate: mirror the live scanner's anomaly firewall. A
            # symbol with any unexplained >35% single-session move in the last
            # 252 bars is not selectable (the move is either an unregistered
            # corporate action or a vendor artifact — never a momentum signal).
            bars["break_recent"] = bars.groupby("symbol")["daily_ret"].transform(
                lambda s: s.abs().rolling(252, min_periods=1).max() > 0.35
            )
            bars["ema_200"] = bars.groupby("symbol")["close"].transform(
                lambda s: s.ewm(span=ema_trend_span, adjust=True, min_periods=min(50, len(s))).mean()
            )
            bars["high_252"] = bars.groupby("symbol")["high"].transform(
                lambda s: s.rolling(lookback_bars, min_periods=min(50, len(s))).max()
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
            bars["pass_retrace"] = bars["close"] >= float(retrace_threshold) * bars["high_252"]
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

            # Execution dates must be real exchange sessions. The raw database
            # contains forward-filled placeholder rows on some non-session dates
            # (e.g. 2026-05-01). Dates after the calendar's last entry are kept,
            # because the calendar can lag the price database.
            db_dates = sorted(bars["date"].unique())
            try:
                from .data_engine import load_trading_calendar
                calendar_dates = set(load_trading_calendar(cal_path=self.base_dir / "data" / "trading_calendar.txt"))
            except Exception:
                calendar_dates = set()
            if calendar_dates:
                calendar_max = max(calendar_dates)
                all_dates = [d for d in db_dates if d in calendar_dates or d > calendar_max]
            else:
                all_dates = db_dates
            calendar_filtered_dates = len(db_dates) - len(all_dates)
            if calendar_filtered_dates:
                self.log(f"Calendar filter removed {calendar_filtered_dates} non-session date(s) from execution.")
            date_to_idx = {d: i for i, d in enumerate(all_dates)}

            self.log(f"Pre-indexing snapshots across universe bars...")
            bars_by_date = {d: g for d, g in bars[bars["date"].isin(set(all_dates))].groupby("date")}

            open_by_date = {}
            close_by_date = {}
            atr_by_date = {}
            valid_dates_by_symbol = {}
            for d in all_dates:
                g = bars_by_date.get(d)
                if g is None:
                    continue
                # Only bars with traded volume are executable; zero-volume rows are
                # forward-filled placeholders and must not be used as fill prices.
                tradable = g[g["volume"] > 0]
                open_by_date[d] = dict(zip(tradable["symbol"], tradable["open"]))
                close_by_date[d] = dict(zip(g["symbol"], g["close"]))
                atr_by_date[d] = dict(zip(g["symbol"], g["atr_14"]))
            for sym, g in bars[bars["volume"] > 0].groupby("symbol"):
                valid_dates_by_symbol[str(sym)] = sorted(g["date"].unique())
            universe_size = int(bars["symbol"].nunique())

            # Breadth gate: refuse a cross-sectional run when too few symbols
            # have the history the strategy needs. This is what makes 2008/2011
            # fail closed instead of producing a misleading "crisis" number.
            warm_counts = bars[bars["date"] <= start_date].groupby("symbol").size()
            if pit_index:
                from .pit_membership import identity_map, members_db_as_of
                _idmap = identity_map(self.base_dir)
                _members = members_db_as_of(
                    str(pit_index), start_date, self.base_dir,
                    symbols=list(warm_counts.index), identity=_idmap,
                )
                eligible_symbols = int(sum(1 for s in _members if warm_counts.get(s, 0) >= 252))
                _min_pit = min_pit_eligible(len(_members))
                if eligible_symbols < _min_pit:
                    raise ValueError(
                        f"INSUFFICIENT_PIT_BREADTH: only {eligible_symbols} point-in-time members of "
                        f"'{pit_index}' have the required 252-bar history on {start_date}; minimum is "
                        f"{_min_pit}. Start later or repair the price history."
                    )
            else:
                eligible_symbols = int((warm_counts >= 252).sum())
                check_breadth(eligible_symbols, universe_source)

            self._prepared_cache = {
                "bars_by_date": bars_by_date,
                "open_by_date": open_by_date,
                "close_by_date": close_by_date,
                "atr_by_date": atr_by_date,
                "all_dates": all_dates,
                "date_to_idx": date_to_idx,
                "delisted_symbols": self.delisted_symbols,
                "bench_bull_map": bench_bull_map,
                "b_df": b_df,
                "valid_dates_by_symbol": valid_dates_by_symbol,
                "calendar_filtered_dates": calendar_filtered_dates,
                "universe_size": universe_size,
                "eligible_symbols": eligible_symbols,
            }
            self._prepared_cache_key = cache_key

        # Identify monthly rebalance signal dates for this run
        test_dates = [d for d in all_dates if d >= start_date]
        df_dates = pd.DataFrame({"date": test_dates})
        df_dates["month"] = df_dates["date"].str[:7]
        if rebalance_schedule == "month_start":
            rebalance_signal_dates = df_dates.groupby("month")["date"].first().tolist()
        else:
            rebalance_signal_dates = df_dates.groupby("month")["date"].last().tolist()

        if len(rebalance_signal_dates) < 2:
            return {"error": "Insufficient rebalance dates in range"}

        # Per-rebalance point-in-time membership. A symbol may enter/leave the
        # index between rebalances; selection uses the snapshot on the signal
        # date, and a holding that leaves is exited at the next rebalance.
        pit_members_by_date = {}
        if pit_index:
            from .pit_membership import identity_map, members_db_as_of
            _idmap = identity_map(self.base_dir)
            _pool = list(universe_symbols or [])
            for _d in rebalance_signal_dates:
                pit_members_by_date[_d] = members_db_as_of(
                    str(pit_index), _d, self.base_dir, symbols=_pool, identity=_idmap
                )
        pit_members_start = (
            len(pit_members_by_date[rebalance_signal_dates[0]]) if pit_index else None
        )
        pit_members_end = (
            len(pit_members_by_date[rebalance_signal_dates[-1]]) if pit_index else None
        )

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
        deferred_fills = 0

        import bisect

        def resolve_fill(symbol: str, earliest_date: str):
            """Returns (fill_date, open_price) on/after earliest_date for a symbol
            that actually traded. Prevents fills on zero-volume placeholder rows."""
            dates = valid_dates_by_symbol.get(symbol)
            if not dates:
                return None, None
            j = bisect.bisect_left(dates, earliest_date)
            if j >= len(dates):
                return None, None
            fill_date = dates[j]
            px = open_by_date.get(fill_date, {}).get(symbol)
            if px is None or not np.isfinite(px) or px <= 0:
                return None, None
            return fill_date, float(px)

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
            pit_members = pit_members_by_date.get(signal_date) if pit_index else None
            if current_holdings:
                sig_slice = bars_by_date.get(signal_date, pd.DataFrame())
                rank_map = {}
                sym_metrics = {}
                if pit_members is not None and not sig_slice.empty:
                    sig_slice = sig_slice[sig_slice["symbol"].isin(pit_members)]
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

                # Invariant (L1-DEF-01): bars price series is already adjusted for splits/bonuses
                # backwards via AnalyticalPriceEngine.derive_analytical_series() at lines 121-133.
                # Entry shares and prices are established in consistent adjusted currency units.
                # Redundant runtime share multiplication removed to preserve exact GIPS accounting parity.

                for sym, h in current_holdings.items():
                    shares = h["shares"]
                    buy_px = h["buy_px"]
                    entry_dt = h["entry_date"]
                    cost_basis = h["cost_basis"]

                    m = sym_metrics.get(sym)
                    rank = rank_map.get(sym, 999999)

                    exit_reason = None
                    if pit_members is not None and sym not in pit_members:
                        exit_reason = "INDEX_REMOVAL"
                    elif m is None or m["close"] <= 0:
                        exit_reason = "NO_DATA"
                    elif m["close"] < float(retrace_threshold) * m["high_252"]:
                        exit_reason = "STOP_52W_HIGH_RETRACEMENT"
                    elif m["close"] < m["ema_200"]:
                        exit_reason = "STOP_200_EMA_BREAK"
                    elif rank > effective_buffer:
                        exit_reason = f"DROPOUT_RANK_{rank}"

                    if exit_reason is None and not random_selection:
                        # Retain position across rebalance (No needless liquidation!)
                        retained_holdings[sym] = h
                    else:
                        # Liquidate on the next session where the scrip actually trades.
                        fill_date, resolved_px = resolve_fill(sym, exec_date)
                        if resolved_px is not None:
                            exit_date = fill_date
                            exit_px = resolved_px
                            if fill_date != exec_date:
                                deferred_fills += 1
                        else:
                            exit_date = exec_date
                            exit_px = c_exec.get(sym) or last_known_close.get(sym, 0.0)
                        if exit_px <= 0:
                            exit_px = 0.0

                        # Distress liquidation haircut for delisted / suspended companies (DEF-07)
                        if sym in getattr(self, "delisted_symbols", set()) and resolved_px is None:
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
                            "exit_date": exit_date,
                            "entry_px": buy_px,
                            "exit_px": exit_px,
                            "entry_price": buy_px,
                            "exit_price": exit_px,
                            "shares": shares,
                            "cost_basis": round(cost_basis, 2),
                            "net_proceeds": round(net_proceeds, 2),
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
                if pit_members is not None:
                    candidates = candidates[candidates["symbol"].isin(pit_members)]
                if "break_recent" in candidates.columns:
                    candidates = candidates[~candidates["break_recent"].fillna(False)]
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
                        fill_date, buy_px = resolve_fill(sym, exec_date)
                        if buy_px is None or buy_px <= 0:
                            continue
                        if fill_date > next_signal_date:
                            continue
                        if fill_date != exec_date:
                            deferred_fills += 1
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
                                "fill_date": fill_date,
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
                                    "entry_date": e.get("fill_date", exec_date),
                                }
                else:
                    target_alloc = investable_cash / len(selected_symbols)
                    for sym in selected_symbols:
                        fill_date, buy_px = resolve_fill(sym, exec_date)
                        if buy_px is not None and buy_px > 0 and fill_date <= next_signal_date:
                            if fill_date != exec_date:
                                deferred_fills += 1
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
                                        "entry_date": fill_date,
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

        # Export trade log and results (isolated output directory)
        reports_dir = self.output_dir
        reports_dir.mkdir(parents=True, exist_ok=True)

        results = {
            "start_date": start_date,
            "end_date": end_date,
            "years": round(n_years, 2),
            "initial_capital": initial_capital,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return * 100.0, 2),
            "cagr_pct": round(cagr, 2),
            "benchmark_name": getattr(self, "benchmark_name", "NIFTY500"),
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
            "universe_mode": universe_label,
            "universe_size": universe_size,
            "universe_source": universe_source,
            "eligible_symbols": int(eligible_symbols),
            "min_eligible_symbols": int(MIN_ELIGIBLE_SYMBOLS),
            "universe_point_in_time": bool(universe_point_in_time),
            "pit_index": str(pit_index) if pit_index else None,
            "pit_source": "nse-historical-membership (CC BY 4.0)" if pit_index else None,
            "pit_members_start": pit_members_start,
            "pit_members_end": pit_members_end,
            "survivorship_bias_risk": bool(survivorship_bias_risk),
            "data_completeness_risk": bool(data_completeness_risk),
            "strict_point_in_time": True,
            "calendar_filtered_dates": int(calendar_filtered_dates),
            "deferred_fills": int(deferred_fills),
            "total_trades": total_closed_trades,
            "win_rate_pct": win_rate,
            "monthly_returns": [float(v) for v in eq_df["ret"].iloc[1:].tolist()],
            "trade_log_path": str(reports_dir / "trade_log.csv"),
        }

        trade_cols = [
            "trade_id", "symbol", "entry_date", "exit_date", "entry_px", "exit_px",
            "shares", "cost_basis", "net_proceeds", "net_pnl", "return_pct", "exit_reason"
        ]
        trades_df = self.build_trades_df(closed_trades, trade_cols)
        trades_df.to_csv(reports_dir / "trade_log.csv", index=False)

        with open(reports_dir / "backtest_results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        return results
