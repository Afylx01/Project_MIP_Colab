"""
tests/test_phase1_features.py
TDD Test Suite for Phase 1 Institutional Workstation Streamlining:
1. Upper Circuit Execution Guard (detects locked ceiling, bypasses new buys, protects held positions).
2. Zerodha Kite 1-Click Basket Order Generator (JSON import + HTML publisher bridge).
3. Consolidated 3-Tier Command Desk & Backward Compatibility.
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

from core.portfolio import (
    PortfolioManager,
    validate_candidate_safety,
    export_kite_basket,
    EMPTY_ORDERS_COLS,
)
from core.data_engine import get_base_dir, get_latest_date


class TestUpperCircuitExecutionGuard:
    """Verifies that stocks locked at exchange Upper Circuit are safely bypassed."""

    def test_upper_circuit_flag_detection_in_candidate_safety(self):
        """Candidate with is_upper_circuit=True must fail candidate safety for new BUY."""
        row_uc = pd.Series({
            "symbol": "HFCL",
            "close": 268.81,
            "high": 268.81,
            "ret_1d": 0.050,
            "allow_buy": True,
            "signal_type": "BUY",
            "corporate_action_status": "CLEAN",
            "security_health": "HEALTHY",
            "reason_code": "PASS",
            "rank": 4,
            "is_upper_circuit": True,
        })
        is_safe, msg, code = validate_candidate_safety(row_uc, top_n=10)
        assert not is_safe, "Candidate locked in Upper Circuit must not pass safety firewall"
        assert "CIRCUIT" in code or "CIRCUIT" in msg.upper()

    def test_upper_circuit_geometric_detection_fallback(self):
        """Even if is_upper_circuit flag is omitted, High == Close with return >= 4.8% triggers guard."""
        row_geo_uc = pd.Series({
            "symbol": "HFCL",
            "close": 268.81,
            "high": 268.81,
            "ret_1d": 0.050,
            "allow_buy": True,
            "signal_type": "BUY",
            "corporate_action_status": "CLEAN",
            "security_health": "HEALTHY",
            "reason_code": "PASS",
            "rank": 4,
        })
        is_safe, msg, code = validate_candidate_safety(row_geo_uc, top_n=10)
        assert not is_safe, "Geometric High==Close with +5.0% return must be detected as Upper Circuit"
        assert "CIRCUIT" in code or "CIRCUIT" in msg.upper()

    def test_liquid_candidate_not_flagged_as_circuit(self):
        """Normal candidate with High > Close or modest return passes safety check."""
        row_normal = pd.Series({
            "symbol": "DIXON",
            "close": 15000.0,
            "high": 15200.0,
            "ret_1d": 0.021,
            "allow_buy": True,
            "signal_type": "BUY",
            "corporate_action_status": "CLEAN",
            "security_health": "HEALTHY",
            "reason_code": "PASS",
            "rank": 1,
            "is_upper_circuit": False,
        })
        is_safe, msg, code = validate_candidate_safety(row_normal, top_n=10)
        assert is_safe, f"Normal liquid candidate should pass safety check: {msg}"

    def test_rebalancer_bypasses_uc_candidate_to_next_rank(self, tmp_path):
        """When Rank 1 candidate is locked at UC, rebalancer must bypass it and pick Rank 2."""
        base_dir = get_base_dir()
        pm = PortfolioManager(base_dir)

        # Synthetic screener dataframe with 3 candidates
        screener_data = [
            {
                "symbol": "LOCKED_UC",
                "security_id": "SEC_LOCKED_UC",
                "close": 100.0,
                "high": 100.0,
                "ret_1d": 0.050,
                "volar_score": 95.0,
                "rank": 1,
                "sector": "TECH",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
                "is_upper_circuit": True,
            },
            {
                "symbol": "LIQUID_PASS",
                "security_id": "SEC_LIQUID_PASS",
                "close": 200.0,
                "high": 205.0,
                "ret_1d": 0.015,
                "volar_score": 90.0,
                "rank": 2,
                "sector": "HEALTHCARE",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
                "is_upper_circuit": False,
            },
        ]
        screener_df = pd.DataFrame(screener_data)

        orders_df = pm.generate_rebalance_orders(
            cash=100000.0,
            capital=100000.0,
            top_n=1,
            screener_df=screener_df,
            prices={"LOCKED_UC": 100.0, "LIQUID_PASS": 200.0},
            allow_research_overrides=True,
            regime_active=False,
        )

        buy_symbols = orders_df[orders_df["action"] == "BUY"]["symbol"].tolist()
        assert "LOCKED_UC" not in buy_symbols, "Locked UC candidate must not be bought"
        assert "LIQUID_PASS" in buy_symbols, "Next ranked liquid candidate should be promoted into basket"

    def test_existing_holding_locked_at_uc_not_force_sold(self):
        """If user already holds a stock that hits UC, it should NOT be force-sold if stops are intact."""
        base_dir = get_base_dir()
        pm = PortfolioManager(base_dir)

        screener_data = [
            {
                "symbol": "HELD_UC",
                "security_id": "SEC_HELD_UC",
                "close": 105.0,
                "high": 105.0,
                "high_252": 110.0,
                "ema_200": 80.0,
                "ret_1d": 0.050,
                "volar_score": 85.0,
                "rank": 5,
                "sector": "ENERGY",
                "allow_buy": True,
                "signal_type": "BUY",
                "corporate_action_status": "CLEAN",
                "security_health": "HEALTHY",
                "reason_code": "PASS",
                "is_upper_circuit": True,
            }
        ]
        screener_df = pd.DataFrame(screener_data)

        orders_df = pm.generate_rebalance_orders(
            cash=50000.0,
            capital=None,
            top_n=5,
            current_holdings={"HELD_UC": 100},
            screener_df=screener_df,
            prices={"HELD_UC": 105.0},
            allow_research_overrides=True,
            regime_active=False,
        )

        sells = orders_df[orders_df["action"] == "SELL"]["symbol"].tolist()
        assert "HELD_UC" not in sells, "Held stock at UC with intact stops must not be exited"
        holds = orders_df[orders_df["action"] == "HOLD"]["symbol"].tolist()
        assert "HELD_UC" in holds, "Held stock at UC should be retained as HOLD"


class TestZerodhaKiteBasketGenerator:
    """Verifies generation of Zerodha Kite Basket JSON and HTML Publisher page."""

    def test_export_kite_basket_creates_valid_json_and_html(self, tmp_path):
        """Checks schema compliance for Zerodha Kite Web and Mobile Publisher."""
        orders_data = [
            {
                "action": "BUY",
                "symbol": "DIXON",
                "security_id": "SEC_DIXON",
                "sector": "ELECTRONICS",
                "close_price": 15000.0,
                "atr_14": 400.0,
                "stop_loss": 14200.0,
                "target_shares": 6,
                "target_value": 90000.0,
                "risk_allocated": 4800.0,
                "stt": 90.0,
                "exchange_turnover": 3.1,
                "brokerage": 27.0,
                "gst": 5.4,
                "stamp_duty": 13.5,
                "total_friction": 139.0,
                "total_cost": 90139.0,
                "reason": "MOMENTUM_ENTRY",
                "reason_code": "PASS",
                "as_of_date": "2026-10-19",
                "source_signal": "SCANNER",
            },
            {
                "action": "SELL",
                "symbol": "STLTECH",
                "security_id": "SEC_STLTECH",
                "sector": "TELECOM",
                "close_price": 880.0,
                "atr_14": 30.0,
                "stop_loss": 0.0,
                "target_shares": 0,
                "target_value": 44000.0,
                "trade_qty": 50,  # 50 shares to sell
                "risk_allocated": 0.0,
                "stt": 44.0,
                "exchange_turnover": 1.5,
                "brokerage": 13.2,
                "gst": 2.6,
                "stamp_duty": 6.6,
                "total_friction": 67.9,
                "total_cost": 43932.1,
                "reason": "DISTRIBUTION_VETO",
                "reason_code": "PASS",
                "as_of_date": "2026-10-19",
                "source_signal": "STOP_EXIT",
            },
            {
                "action": "HOLD",
                "symbol": "BEL",
                "security_id": "SEC_BEL",
                "sector": "DEFENSE",
                "close_price": 300.0,
                "atr_14": 10.0,
                "stop_loss": 280.0,
                "target_shares": 100,
                "target_value": 30000.0,
                "risk_allocated": 2000.0,
                "stt": 0.0,
                "exchange_turnover": 0.0,
                "brokerage": 0.0,
                "gst": 0.0,
                "stamp_duty": 0.0,
                "total_friction": 0.0,
                "total_cost": 30000.0,
                "reason": "BUFFER_RETAINED",
                "reason_code": "PASS",
                "as_of_date": "2026-10-19",
                "source_signal": "BUFFER_RETAIN",
            },
        ]
        orders_df = pd.DataFrame(orders_data)

        json_path, html_path = export_kite_basket(orders_df, base_dir=tmp_path)

        assert json_path.exists(), "kite_basket.json must exist"
        assert html_path.exists(), "kite_basket_execute.html must exist"

        # Validate JSON content
        with open(json_path, "r", encoding="utf-8") as f:
            basket_items = json.load(f)

        assert isinstance(basket_items, list), "Basket JSON must be a list of orders"
        assert len(basket_items) == 2, "Only BUY and SELL actionable orders should be in basket (HOLD excluded)"

        buy_item = next(item for item in basket_items if item["tradingsymbol"] == "DIXON")
        assert buy_item["variety"] == "regular"
        assert buy_item["exchange"] == "NSE"
        assert buy_item["transaction_type"] == "BUY"
        assert buy_item["order_type"] == "MARKET"
        assert buy_item["product"] == "CNC"
        assert buy_item["quantity"] == 6

        sell_item = next(item for item in basket_items if item["tradingsymbol"] == "STLTECH")
        assert sell_item["transaction_type"] == "SELL"
        assert sell_item["quantity"] == 50

        # Validate HTML content
        html_content = html_path.read_text(encoding="utf-8")
        assert "https://kite.zerodha.com/connect/basket" in html_content
        assert "DIXON" in html_content
        assert "STLTECH" in html_content
        assert "Execute" in html_content


class TestConsolidatedMenuDesk:
    """Verifies that main.py exports the 3-Tier Command Desk without breaking legacy handlers."""

    def test_legacy_handler_keys_intact(self):
        """All legacy numerical options (1-18) must map to callable functions in main.py."""
        import main
        assert hasattr(main, "build_menu_handlers"), "main.py should define build_menu_handlers()"
        handlers = main.build_menu_handlers()

        for legacy_key in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16", "17", "18"]:
            assert legacy_key in handlers, f"Legacy handler key '{legacy_key}' must be preserved for backward compatibility"
            assert callable(handlers[legacy_key]), f"Handler for key '{legacy_key}' must be callable"

    def test_action_desk_function_exists(self):
        """main.py must provide run_one_click_eod_action_desk()."""
        import main
        assert hasattr(main, "run_one_click_eod_action_desk"), "main.py must implement run_one_click_eod_action_desk"
        assert callable(main.run_one_click_eod_action_desk)
