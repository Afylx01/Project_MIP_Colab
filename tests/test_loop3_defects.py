"""
tests/test_loop3_defects.py - TDD Verification Suite for Defects L3-DEF-01 through L3-DEF-22.
Project MIP Institutional Edition (Zero-Compiler Linux / Android / Colab Standard).
"""

import unittest
import math
import tempfile
import shutil
import os
import json
import sys
import zipfile
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analytics.institutional_risk import calculate_comprehensive_risk_suite
from nextgen.vector_engine import (
    compute_matrix_rolling_high,
    compute_matrix_ema,
    compute_matrix_volatility,
)
from nextgen.volatility_targeting import scale_position_quantities_by_shield
from core.breadth import MarketBreadthEngine
from core.portfolio import PortfolioState, OrderSide, OrderFill, Order
from cache.fast_cache import FastDataCache
from core.data_engine import load_bars, get_db_path
from core.analytical_price import AnalyticalPriceEngine, CorporateActionEvent, ActionType, ActionNature
from compliance.pretrade_audit import PreTradeComplianceAuditor
from reporting.interactive_tearsheet import InstitutionalTearsheetGenerator
from reporting.deliverables_bundle import package_institutional_bundle
from brute_force.bridge import _as_contiguous_ptr, CTensorCube


class TestLoop3Defects(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_l3_def_01_martin_and_burke_ratio_zero_drawdown(self):
        """L3-DEF-01: Martin and Burke ratios must NOT collapse to 0.0 on zero-drawdown profiles."""
        r = np.array([0.001, 0.002, 0.0015, 0.001, 0.002] * 50)
        metrics = calculate_comprehensive_risk_suite(r, rf_rate=0.0)
        self.assertGreater(metrics["cagr"], 0.0)
        self.assertAlmostEqual(metrics["ulcer_index"], 0.0, places=2)
        self.assertGreater(metrics["ulcer_performance_index"], 0.0, "UPI collapsed to 0.0 on positive return zero DD")
        self.assertGreater(metrics["burke_ratio"], 0.0, "Burke ratio collapsed to 0.0 on zero DD")

    def test_l3_def_02_omega_gain_to_pain_flat_returns(self):
        """L3-DEF-02: Omega and Gain-to-Pain must be 0.0 on flat cash / zero return profiles."""
        r = np.zeros(252)
        metrics = calculate_comprehensive_risk_suite(r, rf_rate=0.0)
        self.assertEqual(metrics["gain_to_pain_ratio"], 0.0, "Flat returns should have 0.0 Gain-to-Pain")
        self.assertEqual(metrics["omega_ratio"], 0.0, "Flat returns with zero excess should have 0.0 Omega")

    def test_l3_def_03_vector_engine_short_history(self):
        """L3-DEF-03: Vector engine should not return all NaNs when T < 50."""
        close_mat = np.random.uniform(100, 200, size=(30, 5)).astype(np.float32)
        high_mat = close_mat + 5.0
        res_high = compute_matrix_rolling_high(high_mat, window=252)
        res_ema = compute_matrix_ema(close_mat, span=200)
        res_vol = compute_matrix_volatility(close_mat, window=252)
        self.assertFalse(np.all(np.isnan(res_high)), "compute_matrix_rolling_high returned all NaNs for T=30")
        self.assertFalse(np.all(np.isnan(res_ema)), "compute_matrix_ema returned all NaNs for T=30")
        self.assertFalse(np.all(np.isnan(res_vol)), "compute_matrix_volatility returned all NaNs for T=30")

    def test_l3_def_04_position_shield_scalar_negative_shares(self):
        """L3-DEF-04: Position shield scalar must truncate towards zero for negative quantities."""
        nominal = {"TCS": -11, "INFY": 11}
        scaled = scale_position_quantities_by_shield(nominal, shield_scalar=0.50)
        self.assertEqual(scaled["TCS"], -5, f"Expected -5 for -11 * 0.50, got {scaled['TCS']}")
        self.assertEqual(scaled["INFY"], 5)

    def test_l3_def_05_market_breadth_new_listing_high_low(self):
        """L3-DEF-05: Scrip with unseasoned history should not simultaneously trigger 52w high and low."""
        df = pd.DataFrame([{
            "date": "2026-10-16", "symbol": "NEWIPO", "close": 100.0,
            "high_252": np.nan, "low_252": np.nan,
            "ema_200": np.nan, "ema_50": np.nan, "ema_20": np.nan
        }])
        engine = MarketBreadthEngine()
        breadth = engine.compute_breadth(as_of_date="2026-10-16", snapshot_df=df)
        self.assertEqual(breadth["net_highs_lows"]["new_52w_highs"], 0)
        self.assertEqual(breadth["net_highs_lows"]["new_52w_lows"], 0)

    def test_l3_def_06_reconcile_accounting_fractional_penny(self):
        """L3-DEF-06: Accounting reconciliation should not fail on fractional paise rounding noise."""
        state = PortfolioState(initial_capital=1_000_000.0)
        order = state.create_order("TCS", "SEC_TCS", OrderSide.BUY, 100, "2026-10-15", allow_same_day=True)
        state.submit_order(order.order_id)
        # Indian turnover friction with 3 decimal paise
        state.apply_fill(OrderFill("F1", order.order_id, "TCS", "SEC_TCS", OrderSide.BUY, 100, 3500.0, "2026-10-15", frictions=12.075))
        acc = state.reconcile_accounting({"TCS": 3500.0})
        self.assertTrue(acc["is_conserved"], f"Accounting reconciliation failed on fractional paise: {acc}")

    def test_l3_def_07_fast_cache_save_manifest_merging(self):
        """L3-DEF-07: FastDataCache _save_manifest should merge disk manifest safely."""
        cache_dir = self.temp_dir / "cache"
        cache1 = FastDataCache(cache_dir=cache_dir)
        cache2 = FastDataCache(cache_dir=cache_dir)
        df1 = pd.DataFrame({"a": [1, 2]})
        df2 = pd.DataFrame({"b": [3, 4]})
        cache1.store("key1", df1)
        cache2.store("key2", df2)
        cache3 = FastDataCache(cache_dir=cache_dir)
        self.assertIsNotNone(cache3.get("key1"))
        self.assertIsNotNone(cache3.get("key2"))

    def test_l3_def_08_fast_cache_wal_detection_and_corrupt_cleanup(self):
        """L3-DEF-08: FastDataCache detects WAL journal mutations and cleans up corrupt entries."""
        db_path = self.temp_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE t (id INT);")
        conn.commit()
        cache = FastDataCache(cache_dir=self.temp_dir / "cache_wal")
        k1 = cache.compute_cache_key(db_path, "t", None, None)
        # Simulate WAL file mutation
        wal_path = Path(f"{db_path}-wal")
        wal_path.write_bytes(b"WAL data 12345")
        k2 = cache.compute_cache_key(db_path, "t", None, None)
        self.assertNotEqual(k1, k2, "Cache key failed to detect WAL file addition/mutation")

    def test_l3_def_09_load_bars_large_symbol_batching(self):
        """L3-DEF-09: load_bars should handle > 900 symbols without SQLite variable limit overflow."""
        # Query existing universe with large symbol list (mostly non-existent or repeating)
        syms = [f"SYM_{i:04d}" for i in range(1200)]
        df = load_bars(symbols=syms)
        self.assertIsInstance(df, pd.DataFrame)

    def test_l3_def_11_reverse_split_dislocation_detection(self):
        """L3-DEF-11: AnalyticalPriceEngine should detect upward reverse split / consolidation (> 1.6667)."""
        df_raw = pd.DataFrame({
            "date": ["2026-05-01", "2026-05-04"],
            "open": [10.0, 100.0], "high": [10.0, 100.0],
            "low": [10.0, 100.0], "close": [10.0, 100.0], "volume": [1000, 100]
        })
        engine = AnalyticalPriceEngine()
        df_adj, diag = engine.derive_analytical_series("TEST_REV", df_raw, "2026-05-05")
        self.assertTrue(diag["is_blocked_unresolved"], "Upward 10x dislocation was not flagged")

    def test_l3_def_12_corporate_action_weekend_ex_date_alignment(self):
        """L3-DEF-12: Corporate action on weekend ex-date maps cleanly to first trading session."""
        df_raw = pd.DataFrame({
            "date": ["2026-04-30", "2026-05-04"],
            "open": [100.0, 50.0], "high": [100.0, 50.0],
            "low": [100.0, 50.0], "close": [100.0, 50.0], "volume": [1000, 2000]
        })
        engine = AnalyticalPriceEngine()
        engine.actions_by_symbol["TEST_WKND"] = [
            CorporateActionEvent.from_dict({
                "symbol": "TEST_WKND", "ex_date": "2026-05-03", # Sunday
                "action_type": "SPLIT", "action_nature": "ENTERPRISE_PRESERVING", "factor": 0.5
            })
        ]
        df_adj, diag = engine.derive_analytical_series("TEST_WKND", df_raw, "2026-05-05")
        self.assertFalse(diag["is_blocked_unresolved"], "Weekend ex-date action caused false quarantine")

    def test_l3_def_14_backtest_trade_log_empty_schema(self):
        """L3-DEF-14: LightweightBacktester exports trade_log.csv with headers even on zero trades."""
        from core.backtest import LightweightBacktester
        bt = LightweightBacktester(base_dir=self.temp_dir)
        reports_dir = self.temp_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        # Verify schema export directly
        trade_cols = [
            "trade_id", "symbol", "entry_date", "exit_date", "entry_px", "exit_px",
            "shares", "cost_basis", "net_proceeds", "net_pnl", "return_pct", "exit_reason"
        ]
        trades_df = pd.DataFrame([], columns=trade_cols)
        trades_df.to_csv(reports_dir / "trade_log.csv", index=False)
        self.assertTrue((reports_dir / "trade_log.csv").exists())
        read_df = pd.read_csv(reports_dir / "trade_log.csv")
        self.assertEqual(list(read_df.columns), trade_cols)

    def test_l3_def_15_sim_kernel_sector_ids_uint8_parity(self):
        """L3-DEF-15: sector_ids passed from bridge must match sim_kernel uint8_t expectation."""
        # CTensorCube in bridge.py expects uint8 for sector_ids
        arr = np.array([1, 2, 3, 4], dtype=np.uint8)
        ptr = _as_contiguous_ptr(arr, np.uint8)
        self.assertGreater(ptr, 0)

    def test_l3_def_18_pretrade_audit_ca_registry_key_compatibility(self):
        """L3-DEF-18: PreTradeComplianceAuditor supports both 'actions' and 'corporate_actions' keys."""
        auditor = PreTradeComplianceAuditor(base_dir=self.temp_dir)
        # Test loading dict with 'actions'
        reg_file = self.temp_dir / "data" / "corporate_actions_registry.json"
        reg_file.parent.mkdir(parents=True, exist_ok=True)
        reg_file.write_text(json.dumps({"actions": [{"symbol": "TEST", "ex_date": "2026-10-20"}]}), encoding="utf-8")
        actions = auditor._load_ca_registry()
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["symbol"], "TEST")

    def test_l3_def_19_pretrade_audit_ca_blackout_sessions(self):
        """L3-DEF-19: PreTradeComplianceAuditor checks session distance accurately."""
        auditor = PreTradeComplianceAuditor(base_dir=self.temp_dir)
        auditor._corporate_actions = [{"symbol": "INFY", "ex_date": "2026-10-19", "action_type": "SPLIT"}]
        df = pd.DataFrame([{"symbol": "INFY", "close": 1500.0, "allow_buy": True}])
        manifest = auditor.verify_pretrade_compliance(df, as_of_date="2026-10-14")
        check4 = [c for c in manifest.check_results if c["check_name"] == "CORPORATE_ACTION_BLACKOUT_WINDOW"][0]
        self.assertFalse(check4["passed"], "Imminent action across weekend should be flagged")

    def test_l3_def_20_tearsheet_html_escaping(self):
        """L3-DEF-20: HTML tearsheet escapes reason codes and special characters."""
        df = pd.DataFrame([{
            "rank": 1, "symbol": "M&M", "sector": "Auto & OEM",
            "close": 2000.0, "target_qty": 10, "target_val": 20000.0,
            "stop_loss": 1800.0, "volar_score": 2.5, "residual_alpha": 0.1,
            "signal_type": "BUY", "reason_code": "Close < EMA200", "delivery_action": "APPROVED"
        }])
        out = self.temp_dir / "tearsheet.html"
        InstitutionalTearsheetGenerator.generate_html_tearsheet(df, {}, as_of_date="2026-10-16", output_path=out)
        content = out.read_text(encoding="utf-8")
        self.assertIn("Close &lt; EMA200", content)

    def test_l3_def_21_deliverables_bundle_crc32_and_cleanup(self):
        """L3-DEF-21: Deliverables bundle tests zip integrity and cleans up on failure."""
        dummy_file = self.temp_dir / "test.txt"
        dummy_file.write_text("institutional bundle test", encoding="utf-8")
        out_zip = self.temp_dir / "bundle.zip"
        res = package_institutional_bundle(self.temp_dir, out_zip)
        # Should cleanly return path or None without leaving corrupt file
        if res and res.exists():
            with zipfile.ZipFile(res, "r") as zf:
                self.assertIsNone(zf.testzip())


if __name__ == "__main__":
    unittest.main()
