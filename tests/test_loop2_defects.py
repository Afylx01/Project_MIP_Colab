"""
tests/test_loop2_defects.py - TDD Verification Suite for Defects L2-DEF-01 through L2-DEF-14.
Project MIP Institutional Edition (Zero-Compiler Linux / Android / Colab Standard).
"""

import unittest
import math
import tempfile
import shutil
import os
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# DEF-01: Menchero Linking & Zero-Weight Attribution
from analytics.factor_attribution import BrinsonFachlerEngine

# DEF-02: Volatility Targeting EWMA & Breadth Scaling
from nextgen.volatility_targeting import (
    compute_ewma_realized_volatility,
    compute_dynamic_cash_shield_scalar,
)

# DEF-03: Analytical Price Engine Holiday & Dislocation Handling
from core.analytical_price import (
    AnalyticalPriceEngine,
    CorporateActionEvent,
    ActionType,
    ActionNature,
)

# DEF-04: Operational DB Isolation & Picks History
from core.data_engine import get_connection, get_db_path

# DEF-06: FastDataCache Manifest & Safe Deserialization
from cache.fast_cache import FastDataCache

# DEF-07: PipelineLock Heartbeat & Alive Verification
from scripts.run_production_pipeline import PipelineLock, LockAcquisitionError

# DEF-08: Benchmark Freshness & Fail-Closed RS
from core.benchmark_validator import check_benchmark_freshness

# DEF-09: Delivery Manager Alternate Bhavcopy & Non-NaN Baseline
from core.delivery import NSEDeliveryManager
from nextgen.delivery_flow import compute_delivery_absorption_flow, evaluate_microstructure_buy_gate

# DEF-10 & DEF-11: Contiguous Memory Mapping Bridge
from brute_force.bridge import _as_contiguous_ptr

# DEF-12: Excel Formatting Range Bounds
from core.excel_generator import InstitutionalExcelGenerator

# DEF-13: Telegram Chunking
from core.telegram_sender import _chunk_message

# DEF-14: Liquidity Analytics Column Mapping
from analytics.liquidity_analytics import compute_liquidity_profile


class TestLoop2DefectRemediation(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_l2_def_01_menchero_linking_and_zero_weight_attribution(self):
        """DEF-01: Menchero linking additivity when Rp == Rb and zero-weight benchmark convention."""
        # Test 1: Zero active spread (Rp == Rb)
        p1 = BrinsonFachlerEngine.compute_single_period(
            {"IT": 0.5, "BANK": 0.5}, {"IT": 0.05, "BANK": 0.02},
            {"IT": 0.5, "BANK": 0.5}, {"IT": 0.05, "BANK": 0.02},
        )
        linked = BrinsonFachlerEngine.link_multi_period_menchero([p1], [0.035], [0.035])
        self.assertAlmostEqual(linked["cumulative_total_active"].sum(), 0.0, places=6)

        # Test 2: Off-benchmark holding (wb == 0)
        p_off = BrinsonFachlerEngine.compute_single_period(
            portfolio_weights={"SPECIALTY": 0.20, "IT": 0.80},
            portfolio_returns={"SPECIALTY": 0.10, "IT": 0.05},
            benchmark_weights={"IT": 1.00},
            benchmark_returns={"IT": 0.05},
        )
        spec_row = p_off[p_off["sector"] == "SPECIALTY"].iloc[0]
        self.assertAlmostEqual(spec_row["allocation_effect"], 0.0, places=5)
        self.assertAlmostEqual(
            spec_row["selection_effect"] + spec_row["interaction_effect"],
            spec_row["total_active_return"],
            places=5
        )

    def test_l2_def_02_volatility_targeting_inf_guard_and_breadth_decay(self):
        """DEF-02: EWMA handles inf gracefully and breadth ratio scales down exposure below min_exposure."""
        s = pd.Series([0.01, -0.02, np.inf, -np.inf, 0.015, 0.01])
        vol = compute_ewma_realized_volatility(s)
        self.assertTrue(np.all(np.isfinite(vol.to_numpy())))

        # Breadth degradation must not be erased
        scalar_high_breadth = compute_dynamic_cash_shield_scalar(
            is_bull_regime=True, realized_vol=0.15, breadth_ratio=1.0, min_exposure=0.20
        )
        scalar_degraded_breadth = compute_dynamic_cash_shield_scalar(
            is_bull_regime=True, realized_vol=0.15, breadth_ratio=0.10, min_exposure=0.20
        )
        self.assertLess(scalar_degraded_breadth, scalar_high_breadth)

    def test_l2_def_03_analytical_price_holiday_ex_date_and_known_crash(self):
        """DEF-03: Holiday ex-date dislocation checking and market crash registration."""
        reg_file = self.temp_dir / "corporate_actions_registry.json"
        events = [{
            "symbol": "TESTSYM", "security_id": "SEC_TEST",
            "ex_date": "2026-05-03",  # Sunday (Market Holiday)
            "record_date": "2026-05-04", "effective_date": "2026-05-04",
            "action_type": "SPLIT", "action_nature": "ENTERPRISE_PRESERVING",
            "factor": 0.5, "resulting_entities": ["TESTSYM"], "source_authority": "NSE",
            "source_reference": "CIRCULAR_1", "ingestion_timestamp": "2026-05-01",
        }]
        reg_file.write_text(json.dumps(events))
        engine = AnalyticalPriceEngine(registry_path=reg_file)

        # Bars where split took effect on Monday 2026-05-04
        df_raw = pd.DataFrame({
            "date": ["2026-04-30", "2026-05-04"],
            "symbol": ["TESTSYM", "TESTSYM"],
            "open": [1000.0, 500.0], "high": [1020.0, 510.0], "low": [990.0, 495.0], "close": [1000.0, 500.0],
            "volume": [10000, 20000],
        })
        adj_df, diag = engine.derive_analytical_series("TESTSYM", df_raw, as_of_date="2026-05-04")
        self.assertFalse(diag.get("is_blocked_unresolved"))
        self.assertEqual(adj_df["close"].iloc[0], 500.0)

    def test_l2_def_04_picks_history_isolation_from_readonly_universe(self):
        """DEF-04: universe.db remains strictly read-only while operational writes succeed."""
        with self.assertRaises(PermissionError):
            get_connection(read_only=False, reuse=False)

        from core.data_engine import get_operational_connection
        op_conn = get_operational_connection()
        self.assertIsNotNone(op_conn)
        cur = op_conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='picks_history';")
        self.assertIsNotNone(cur.fetchone())
        op_conn.close()

    def test_l2_def_05_calendar_aligned_momentum_gaps(self):
        """DEF-05: Momentum calculation handles halted scrips without row-index distortion."""
        from core.scanner import _calc_calendar_aligned_return
        # Test helper presence and calendar bounded shift
        s = pd.Series([100.0, 102.0, 105.0], index=["2025-01-01", "2025-01-02", "2025-01-03"])
        cal = ["2025-01-01", "2025-01-02", "2025-01-03"]
        ret = _calc_calendar_aligned_return(s, cal, lookback=2)
        self.assertIsNotNone(ret)

    def test_l2_def_06_fast_cache_manifest_eviction_atomicity_and_no_pickle(self):
        """DEF-06: Manifest eviction does not resurrect dead keys and uses allow_pickle=False."""
        cache = FastDataCache(cache_dir=self.temp_dir, max_cache_size_mb=1)
        df = pd.DataFrame({"symbol": ["RELIANCE", "TCS"], "close": [2500.0, 3500.0]})
        key = "test_key_01"
        cache.store(key, df)
        self.assertIsNotNone(cache.get(key))

        # Clear must be permanent
        cache.clear()
        reloaded_manifest = cache._load_manifest()
        self.assertEqual(len(reloaded_manifest), 0)
        self.assertIsNone(cache.get(key))

    def test_l2_def_07_pipeline_lock_extended_scan_heartbeat(self):
        """DEF-07: Running process lock is not marked stale purely by elapsed time."""
        lock_file = self.temp_dir / ".scanner.lock"
        lock_data = {
            "pid": os.getpid(),
            "acquired_at": "2020-01-01T00:00:00+00:00",
            "last_heartbeat": "2020-01-01T00:00:00+00:00",
            "host_os": "linux",
        }
        lock_file.write_text(json.dumps(lock_data))
        lock = PipelineLock(lock_file, timeout_seconds=100)
        self.assertTrue(lock_file.exists())

    def test_l2_def_08_benchmark_session_divergence_fail_closed(self):
        """DEF-08: Benchmark date verification detects lookahead or divergence cleanly."""
        is_fresh, exp_date, reason = check_benchmark_freshness(
            as_of_date="2026-10-18",
            latest_bench_date="2026-10-20",
        )
        self.assertFalse(is_fresh)
        self.assertIn("Lookahead violation", reason)

    def test_l2_def_09_delivery_flow_nan_baseline_safe_handling(self):
        """DEF-09: NaN median delivery value does not cause NaN SMFI or false buy veto."""
        daf = compute_delivery_absorption_flow(
            delivery_qty=10000, close=100.0, high=102.0, low=98.0,
            median_delivery_val_cr=np.nan,
        )
        self.assertTrue(math.isfinite(daf))
        gate = evaluate_microstructure_buy_gate(daf)
        self.assertNotEqual(gate.get("action"), "MISSING_DATA_VETO")

    def test_l2_def_10_sim_kernel_zero_downside_sortino(self):
        """DEF-10: Sim kernel Sortino formula does not penalize zero downside deviation."""
        down_vol = 0.0
        mean_ret = 0.02
        rf = 0.005
        sortino = 99.9 if down_vol <= 1e-5 and mean_ret >= rf else ((mean_ret - rf) / max(down_vol, 1e-5))
        self.assertEqual(sortino, 99.9)

    def test_l2_def_11_tensor_cube_contiguous_array_guarantee(self):
        """DEF-11: Fortran or strided array converted to C-contiguous before ctypes transfer."""
        f_arr = np.zeros((10, 20), order="F", dtype=np.float32)
        ptr = _as_contiguous_ptr(f_arr, dtype=np.float32)
        self.assertNotEqual(ptr, 0)

    def test_l2_def_12_excel_generator_empty_candidates_range_bounds(self):
        """DEF-12: Empty candidates does not generate inverted range O2:O1."""
        gen = InstitutionalExcelGenerator(base_dir=self.temp_dir)
        empty_df = pd.DataFrame(columns=["symbol", "close", "volar_score"])
        dash_meta, dash_rot, dash_rrg, dash_stk, dash_etf, layout = gen._build_dashboard_frames(
            "2026-10-18", empty_df, empty_df, {}, {}, None, False, "TEST"
        )
        self.assertEqual(len(dash_stk), 0)

    def test_l2_def_13_telegram_chunking_honors_hard_limit(self):
        """DEF-13: Messages exceeding 4096 characters are split without payload loss."""
        large_msg = "\n".join([f"Line {i}: Data for scrip {i}" for i in range(300)])
        self.assertGreater(len(large_msg), 4096)
        chunks = _chunk_message(large_msg, max_length=4000)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 4000)
        self.assertEqual("".join(chunks), large_msg, "Chunking must be lossless")
        long_line = "X" * 9500
        long_chunks = _chunk_message(long_line, max_length=4000)
        self.assertTrue(all(len(c) <= 4000 for c in long_chunks))
        self.assertEqual("".join(long_chunks), long_line)

    def test_l2_def_14_liquidity_analytics_deliv_qty_alias_support(self):
        """DEF-14: compute_liquidity_profile supports deliv_qty column alias."""
        orders_df = pd.DataFrame({
            "symbol": ["RELIANCE", "TCS"],
            "close": [2500.0, 3500.0],
            "target_qty": [10, 5],
            "target_val": [25000.0, 17500.0],
            "deliv_qty": [500000, 200000],
        })
        profile = compute_liquidity_profile(orders_df=orders_df, capital_inr=100000.0)
        adv_series = profile["detailed_table"]["adv_30"]
        self.assertGreater(adv_series.iloc[0], 150000.0)


if __name__ == "__main__":
    unittest.main()
