"""
tests/test_phase2_features.py
TDD Test Suite for Phase 2: Quantitative Factor Fusion & Tax Awareness
1. Composite Alpha Score (CAS) Engine (Price Momentum + Residual Momentum + Delivery Flow).
2. Delivery Distribution Priority Veto for Existing Holdings (Resolves the STLTECH Paradox).
3. Turnover Deadband Filter (Suppresses micro-trades < ₹2,500 / 1.5% NAV drift).
4. Finance Act 2024 STCG/LTCG Tax-Aware Holding Hurdle.
"""

import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import pytest
import pandas as pd
import numpy as np

from nextgen.composite_alpha import (
    compute_robust_mad_zscore,
    compute_composite_alpha_score,
)
from core.portfolio import PortfolioManager
from core.data_engine import get_base_dir


class TestCompositeAlphaEngine:
    """Verifies cross-sectional robust factor fusion into Composite Alpha Score."""

    def test_robust_mad_zscore_computation(self):
        """Tests that MAD z-scoring standardizes and clips extreme outliers."""
        s = pd.Series([10.0, 12.0, 11.0, 10.5, 11.5, 100.0])  # 100 is outlier
        z = compute_robust_mad_zscore(s, clip_val=3.0)
        assert len(z) == 6
        assert z.iloc[-1] == 3.0  # Clipped at +3.0
        assert np.isclose(z.median(), 0.0, atol=0.2)

    def test_composite_alpha_weight_blending(self):
        """Tests that CAS properly blends Volar, Residual Mom, and Delivery Flow."""
        df = pd.DataFrame([
            {"symbol": "SYM_A", "volar_score": 80.0, "residual_mom_score": 2.5, "deliv_flow_score": 3.0},
            {"symbol": "SYM_B", "volar_score": 85.0, "residual_mom_score": -1.0, "deliv_flow_score": -2.0},
            {"symbol": "SYM_C", "volar_score": 60.0, "residual_mom_score": 1.0, "deliv_flow_score": 1.0},
        ])
        res = compute_composite_alpha_score(df, weights={"total_momentum": 0.45, "residual_momentum": 0.35, "delivery_flow": 0.20})
        assert "composite_alpha_score" in res.columns
        assert "composite_rank" in res.columns
        # SYM_A should rank #1 because it is high across all 3 factors
        assert res.sort_values("composite_rank").iloc[0]["symbol"] == "SYM_A"


class TestDeliveryDistributionHoldingVeto:
    """Verifies that institutional distribution immediately exits held stocks (STLTECH fix)."""

    def test_delivery_distribution_overrides_holding_buffer(self):
        """
        If a held stock triggers distribution, its Rank 40 exit buffer is revoked
        and an immediate SELL ticket is generated.
        """
        base_dir = get_base_dir()
        pm = PortfolioManager(base_dir)

        # Held stock STLTECH is inside buffer (Rank 15), but has DISTRIBUTION veto
        screener_data = [
            {
                "symbol": "STLTECH",
                "security_id": "SEC_STLTECH",
                "close": 880.0,
                "high": 900.0,
                "high_252": 950.0,
                "ema_200": 700.0,
                "ret_1d": -0.025,
                "volar_score": 88.0,
                "rank": 15,  # Well inside Rank 40 buffer!
                "sector": "TELECOM",
                "allow_buy": False,
                "signal_type": "DISTRIBUTION_VETO",
                "delivery_action": "🔴 DISTRIBUTION",
                "is_delivery_vetoed": True,
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
            },
            {
                "symbol": "CLEAN_BUY",
                "security_id": "SEC_CLEAN_BUY",
                "close": 500.0,
                "high": 510.0,
                "ret_1d": 0.010,
                "volar_score": 85.0,
                "rank": 1,
                "sector": "TECH",
                "allow_buy": True,
                "signal_type": "BUY",
                "delivery_action": "🟢 ACCUMULATION",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
            }
        ]
        screener_df = pd.DataFrame(screener_data)

        orders_df = pm.generate_rebalance_orders(
            cash=100000.0,
            capital=100000.0,
            top_n=2,
            current_holdings={"STLTECH": 50},
            screener_df=screener_df,
            prices={"STLTECH": 880.0, "CLEAN_BUY": 500.0},
            allow_research_overrides=True,
            regime_active=False,
            enforce_delivery_exit_veto=True,
        )

        sells = orders_df[orders_df["action"] == "SELL"]
        sell_syms = sells["symbol"].tolist()
        assert "STLTECH" in sell_syms, "STLTECH must be liquidated due to delivery distribution veto"
        st_sell = sells[sells["symbol"] == "STLTECH"].iloc[0]
        assert "DISTRIBUTION" in str(st_sell["reason"]).upper()


class TestTurnoverDeadbandAndTaxAwareRebalancing:
    """Verifies deadband filtering on micro-adjustments and LTCG tax protection."""

    def test_turnover_deadband_suppresses_small_drift(self):
        """If position value drift is < ₹2,500 or < 1.5% NAV, trade is suppressed."""
        base_dir = get_base_dir()
        pm = PortfolioManager(base_dir)

        screener_data = [
            {
                "symbol": "HELD_STOCK",
                "security_id": "SEC_HELD_STOCK",
                "close": 1000.0,
                "high": 1020.0,
                "high_252": 1100.0,
                "ema_200": 800.0,
                "ret_1d": 0.005,
                "volar_score": 90.0,
                "rank": 1,
                "sector": "AUTO",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
            }
        ]
        screener_df = pd.DataFrame(screener_data)

        # NAV = ₹1,00,000. Target 1 stock = ₹1,00,000 (100 shares).
        # Currently holds 99 shares (Value = ₹99,000). Drift = 1 share = ₹1,000 (< ₹2,500).
        orders_df = pm.generate_rebalance_orders(
            cash=1000.0,
            capital=100000.0,
            top_n=1,
            current_holdings={"HELD_STOCK": 99},
            screener_df=screener_df,
            prices={"HELD_STOCK": 1000.0},
            allow_research_overrides=True,
            regime_active=False,
            min_trade_amount_inr=2500.0,
        )

        held_order = orders_df[orders_df["symbol"] == "HELD_STOCK"].iloc[0]
        # Trade should be suppressed to avoid ₹1,000 micro-trade
        assert held_order["action"] == "HOLD"
        assert int(held_order["trade_qty"]) == 0

    def test_tax_aware_rebalance_protects_near_ltcg_gain(self):
        """Holding held for 320 days with large gain is protected against marginal swap."""
        base_dir = get_base_dir()
        pm = PortfolioManager(base_dir)

        # Existing holding HELD_NEAR_LTCG has held 320 days, large unrealized profit
        # Incoming candidate NEW_CAND has slightly better rank (#1 vs #2), but not enough to cover 7.5% tax gap
        screener_data = [
            {
                "symbol": "NEW_CAND",
                "security_id": "SEC_NEW_CAND",
                "close": 200.0,
                "high": 205.0,
                "volar_score": 92.0,
                "composite_alpha_score": 1.25,
                "rank": 1,
                "sector": "FINANCE",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
            },
            {
                "symbol": "HELD_NEAR_LTCG",
                "security_id": "SEC_HELD_NEAR_LTCG",
                "close": 500.0,
                "high": 510.0,
                "high_252": 520.0,
                "ema_200": 350.0,
                "volar_score": 90.0,
                "composite_alpha_score": 1.20,
                "rank": 45,  # Dropped below Rank 40 buffer!
                "sector": "TECH",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
            }
        ]
        screener_df = pd.DataFrame(screener_data)

        # Detailed holdings with purchase metadata
        detailed_holdings = {
            "HELD_NEAR_LTCG": {
                "shares": 100,
                "days_held": 320,  # 45 days away from 365-day LTCG threshold
                "purchase_price": 300.0,  # ₹200/share unrealized profit!
            }
        }

        orders_df = pm.generate_rebalance_orders(
            cash=10000.0,
            capital=60000.0,
            top_n=1,  # Only 1 slot available!
            current_holdings=detailed_holdings,
            screener_df=screener_df,
            prices={"NEW_CAND": 200.0, "HELD_NEAR_LTCG": 500.0},
            allow_research_overrides=True,
            regime_active=False,
            tax_aware_rebalance=True,
        )

        sells = orders_df[orders_df["action"] == "SELL"]["symbol"].tolist()
        assert "HELD_NEAR_LTCG" not in sells, "Held stock near LTCG threshold with large gains should not be swapped for marginal alpha"
