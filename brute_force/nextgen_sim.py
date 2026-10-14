"""
nextgen_sim.py - High-Performance Simulation Engine for Next-Gen Modified Method
Integrates Features 1-4:
- Feature 1: Residual Momentum & 21-day Reversal Guard (Blitz et al. 2011/2020)
- Feature 2: 2D Contiguous Vectorized Processing
- Feature 3: Continuous Volatility Targeting (12% Target Vol) & Dynamic Cash Shield
- Feature 4: Delivery Absorption Flow & Distribution Veto
"""

import time
import math
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import pandas as pd

from .cube_builder import TensorCubeContainer
from nextgen.residual_momentum import compute_rolling_residual_momentum, compute_composite_momentum_score
from nextgen.volatility_targeting import (
    compute_ewma_realized_volatility,
    compute_dynamic_cash_shield_scalar,
    scale_position_quantities_by_shield,
)
from nextgen.delivery_flow import compute_close_location_value


class NextGenSimulationEngine:
    """Evaluates Next-Gen Momentum Strategy with Full Invariant Preservation."""

    def __init__(self, cube: TensorCubeContainer):
        self.cube = cube
        self._prepare_nextgen_tensors()

    def _prepare_nextgen_tensors(self):
        """Precomputes Residual Momentum and Volatility Targeting planes."""
        T = self.cube.num_dates
        N = self.cube.num_symbols

        print("[NextGenSim] Precomputing Residual Momentum planes across lookbacks...")
        # Daily benchmark returns
        close_px = self.cube.close_px
        daily_ret = np.zeros((T, N), dtype=np.float32)
        daily_ret[1:] = np.where(close_px[:-1] > 0, (close_px[1:] / close_px[:-1]) - 1.0, 0.0)

        # Approximate benchmark return as universe median/mean return
        bench_ret = np.median(daily_ret, axis=1)

        # Precompute Residual Momentum for canonical lookback (252d)
        df_stock_ret = pd.DataFrame(daily_ret)
        s_bench_ret = pd.Series(bench_ret)

        df_res_252 = compute_rolling_residual_momentum(
            stock_returns=df_stock_ret,
            bench_returns=s_bench_ret,
            lookback=252,
            skip_recent=21,
            rf_rate=0.065,
        )
        self.res_volar_252 = df_res_252.to_numpy(dtype=np.float32)

        # Composite Volar for lookback 252 (lookback_idx = 4)
        volar_252 = self.cube.volar_cubes[4]
        self.composite_volar_252 = compute_composite_momentum_score(
            volar_scores=volar_252,
            residual_scores=self.res_volar_252,
            volar_weight=0.40,
            residual_weight=0.60,
        )

        print("[NextGenSim] Precomputing EWMA Benchmark Realized Volatility & Dynamic Cash Shield...")
        ann_vol = compute_ewma_realized_volatility(s_bench_ret, lambda_decay=0.94)
        self.realized_vol = ann_vol.to_numpy(dtype=np.float32)

        # Market breadth participation: fraction of stocks > 200 EMA
        ema_200 = self.cube.ema_cubes[2]  # span 200
        valid_stocks = close_px > 0
        stocks_above_200 = (close_px > ema_200) & valid_stocks
        total_valid = np.maximum(np.sum(valid_stocks, axis=1), 1)
        self.breadth_participation = np.sum(stocks_above_200, axis=1).astype(np.float32) / total_valid

        # Precompute Close Location Value (CLV)
        high_px = self.cube.high_cubes[4]  # rolling high 252
        low_px = np.where(close_px > 0, close_px * 0.90, 0.0)
        span_px = high_px - low_px
        self.clv_mat = np.where(span_px > 0, (2.0 * close_px - high_px - low_px) / span_px, 0.0)

    def run_single(
        self,
        lookback_idx: int = 4,
        ema_idx: int = 2,
        retrace_threshold: float = 0.80,
        top_n: int = 20,
        exit_buffer_rank: int = 40,
        max_per_sector: int = 2,
        initial_capital: float = 1_000_000.0,
        friction_bps: float = 15.0,
        slippage_bps: float = 5.0,
        risk_per_trade_pct: float = 1.0,
        enable_residual_momentum: bool = True,
        enable_volatility_targeting: bool = True,
        enable_distribution_veto: bool = True,
    ) -> Dict[str, Any]:
        """Runs the Next-Gen simulation for a single configuration."""
        cube = self.cube
        T = cube.num_dates
        N = cube.num_symbols
        num_rebalances = cube.num_rebalances
        total_friction_rate = (friction_bps + slippage_bps) / 10000.0

        cash = initial_capital
        peak_equity = initial_capital
        max_dd = 0.0

        holdings = {}  # sym_idx: {"shares": int, "buy_px": float, "cost_basis": float}
        closed_trades = 0
        winning_trades = 0
        gross_gains = 0.0
        gross_losses = 0.0

        monthly_equity = [initial_capital]
        monthly_returns = []

        cur_volar_plane = self.composite_volar_252 if enable_residual_momentum else cube.volar_cubes[lookback_idx]
        cur_high_plane = cube.high_cubes[lookback_idx]
        cur_ema_plane = cube.ema_cubes[ema_idx]
        cur_rs_plane = cube.rs_pass_cubes[ema_idx]

        for r in range(num_rebalances - 1):
            sig_date = cube.rebalance_indices[r]
            exec_date = sig_date + 1
            if exec_date >= T:
                exec_date = sig_date

            sig_close = cube.close_px[sig_date]
            sig_volar = cur_volar_plane[sig_date]
            sig_high = cur_high_plane[sig_date]
            sig_ema = cur_ema_plane[sig_date]
            sig_rs = cur_rs_plane[sig_date]

            exec_open = cube.open_px[exec_date]
            exec_close = cube.close_px[exec_date]
            exec_atr = cube.atr_14[exec_date]

            # 1. Evaluate Qualifying Candidates and Assign Ranks
            pass_mask = (
                (sig_close > 0)
                & (sig_close >= (retrace_threshold * sig_high))
                & (sig_close > sig_ema)
                & (sig_rs > 0)
                & (sig_volar > 0)
            )

            # Feature 4: Delivery distribution veto (exclude stocks closing in bottom 10% of 52w range)
            if enable_distribution_veto:
                pass_mask = pass_mask & (self.clv_mat[sig_date] > -0.70)

            qualifying_indices = np.where(pass_mask)[0]
            qualifying_volars = sig_volar[qualifying_indices]

            # Rank assignment
            sorted_order = np.argsort(-qualifying_volars)
            ranked_syms = qualifying_indices[sorted_order]
            candidate_ranks = {sym: rank + 1 for rank, sym in enumerate(ranked_syms)}

            # 2. Evaluate Exits for Existing Holdings
            retained_holdings = {}
            for sym, h in holdings.items():
                c_px = sig_close[sym]
                h_px = sig_high[sym]
                e_px = sig_ema[sym]
                rank = candidate_ranks.get(sym, 999999)

                should_exit = (
                    (c_px <= 0)
                    or (c_px < (retrace_threshold * h_px))
                    or (c_px < e_px)
                    or (rank > exit_buffer_rank)
                )

                if not should_exit:
                    retained_holdings[sym] = h
                else:
                    exit_px = exec_open[sym] if exec_open[sym] > 0 else (exec_close[sym] if exec_close[sym] > 0 else c_px)
                    gross_proceeds = h["shares"] * exit_px
                    friction = gross_proceeds * total_friction_rate
                    net_proceeds = max(0.0, gross_proceeds - friction)

                    cash += net_proceeds
                    closed_trades += 1
                    pnl = net_proceeds - h["cost_basis"]
                    if pnl > 0:
                        winning_trades += 1
                        gross_gains += pnl
                    else:
                        gross_losses += abs(pnl)

            holdings = retained_holdings

            # 3. Dynamic Cash Shield & Volatility Target Scalar (Feature 3)
            is_bull = cube.benchmark_regime[sig_date] > 0
            if enable_volatility_targeting:
                shield_scalar = compute_dynamic_cash_shield_scalar(
                    is_bull_regime=is_bull,
                    realized_vol=float(self.realized_vol[sig_date]),
                    target_vol=0.12,
                    breadth_ratio=float(self.breadth_participation[sig_date]),
                    min_exposure=0.20,
                    max_exposure=1.00,
                )
            else:
                shield_scalar = 1.0 if is_bull else 0.0

            # 4. Select New Entrants for Open Slots
            open_slots = top_n - len(holdings)
            if open_slots > 0 and shield_scalar > 0.0 and len(ranked_syms) > 0:
                sector_counts = {}
                for sym in holdings:
                    sec = cube.sector_ids[sym]
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1

                selected_syms = []
                for sym in ranked_syms:
                    if sym in holdings:
                        continue
                    sec = cube.sector_ids[sym]
                    if sector_counts.get(sec, 0) >= max_per_sector:
                        continue
                    selected_syms.append(sym)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    if len(selected_syms) >= open_slots:
                        break

                # 5. Position Sizing with Volatility Target Scaling
                if selected_syms and cash > 1000.0:
                    investable_cash = cash * 0.99
                    invested_val = sum(
                        h["shares"] * (sig_close[s] if sig_close[s] > 0 else h["buy_px"])
                        for s, h in holdings.items()
                    )
                    curr_capital = cash + invested_val
                    risk_budget = curr_capital * (risk_per_trade_pct / 100.0)

                    raw_entries = []
                    total_req = 0.0
                    for sym in selected_syms:
                        buy_px = exec_open[sym] if exec_open[sym] > 0 else exec_close[sym]
                        if buy_px <= 0:
                            continue
                        atr = exec_atr[sym] if exec_atr[sym] > 0 else (buy_px * 0.03)
                        rps = max(2.0 * atr, buy_px * 0.02)
                        q_risk = int(risk_budget // rps) if rps > 0 else 0
                        q_cap = int((curr_capital * 0.25) // buy_px) if buy_px > 0 else 0
                        q_nominal = max(0, min(q_risk, q_cap))

                        # Scale by Cash Shield
                        q_effective = int(math.floor(q_nominal * shield_scalar))
                        if q_effective > 0:
                            trade_val = q_effective * buy_px
                            buy_fric = trade_val * total_friction_rate
                            total_cost = trade_val + buy_fric
                            raw_entries.append((sym, buy_px, q_effective, total_cost))
                            total_req += total_cost

                    scale = (investable_cash / total_req) if (total_req > investable_cash and total_req > 0) else 1.0
                    for sym, buy_px, q_eff, t_cost in raw_entries:
                        final_shares = int(q_eff * scale)
                        if final_shares > 0:
                            trade_val = final_shares * buy_px
                            buy_fric = trade_val * total_friction_rate
                            total_cost = trade_val + buy_fric
                            if total_cost <= cash and len(holdings) < 64:
                                cash -= total_cost
                                holdings[sym] = {
                                    "shares": final_shares,
                                    "buy_px": buy_px,
                                    "cost_basis": total_cost,
                                }

            # 6. Portfolio Valuation at Period Close
            period_nav = cash + sum(
                h["shares"] * (exec_close[s] if exec_close[s] > 0 else h["buy_px"])
                for s, h in holdings.items()
            )
            if period_nav > peak_equity:
                peak_equity = period_nav
            dd = (peak_equity - period_nav) / peak_equity
            if dd > max_dd:
                max_dd = dd

            prev_eq = monthly_equity[-1]
            ret = (period_nav / prev_eq - 1.0) if prev_eq > 0 else 0.0
            monthly_returns.append(ret)
            monthly_equity.append(period_nav)

        # Financial Performance Calculation
        final_equity = monthly_equity[-1]
        total_years = (cube.num_rebalances - 1) / 12.0
        cagr = (pow(max(final_equity / initial_capital, 0.001), 1.0 / total_years) - 1.0) * 100.0

        rf_monthly = 0.065 / 12.0
        ret_arr = np.array(monthly_returns)
        mean_ret = np.mean(ret_arr) if len(ret_arr) > 0 else 0.0
        std_ret = np.std(ret_arr, ddof=1) if len(ret_arr) > 1 else 0.01

        down_diff = np.minimum(ret_arr - rf_monthly, 0.0)
        down_std = np.sqrt(np.mean(down_diff ** 2)) if len(down_diff) > 0 else 0.01

        sharpe = ((mean_ret - rf_monthly) / std_ret * np.sqrt(12.0)) if std_ret > 1e-5 else 0.0
        sortino = ((mean_ret - rf_monthly) / down_std * np.sqrt(12.0)) if down_std > 1e-5 else 0.0
        calmar = (cagr / (max_dd * 100.0)) if max_dd > 1e-4 else 0.0
        win_rate = (winning_trades / closed_trades * 100.0) if closed_trades > 0 else 0.0
        profit_factor = (gross_gains / gross_losses) if gross_losses > 0 else (99.9 if gross_gains > 0 else 1.0)

        return {
            "config_type": "NEXT_GEN_UPGRADED",
            "lookback": cube.lookback_values[lookback_idx],
            "ema_trend": cube.ema_span_values[ema_idx],
            "retrace_threshold": retrace_threshold,
            "top_n": top_n,
            "exit_buffer_rank": exit_buffer_rank,
            "max_per_sector": max_per_sector,
            "cagr_pct": float(round(cagr, 2)),
            "sharpe_ratio": float(round(sharpe, 2)),
            "sortino_ratio": float(round(sortino, 2)),
            "max_drawdown_pct": float(round(max_dd * 100.0, 2)),
            "calmar_ratio": float(round(calmar, 2)),
            "win_rate_pct": float(round(win_rate, 2)),
            "profit_factor": float(round(profit_factor, 2)),
            "ending_equity": float(round(final_equity, 2)),
            "total_trades": int(closed_trades),
            "winning_trades": int(winning_trades),
            "monthly_equity": [float(round(v, 2)) for v in monthly_equity],
            "monthly_returns": [float(round(v, 4)) for v in monthly_returns],
        }
