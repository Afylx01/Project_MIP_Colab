"""
Test suite proving all 19 latent defects from Stage 1 Defect Discovery (L4-DEF-01 through L4-DEF-19).
Following TDD protocol: author failing contract tests first to demonstrate flaws.
"""

import os
import sys
import math
import gzip
import time
import shutil
import sqlite3
import datetime
import pytest
import numpy as np
import pandas as pd
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ==============================================================================
# L4-DEF-01: Enterprise-Altering Action Early Exit Skips Subsequent Preserving Splits
# ==============================================================================
def test_l4_def_01_preserving_split_after_enterprise_altering(tmp_path):
    from core.analytical_price import AnalyticalPriceEngine, CorporateActionEvent, ActionNature, ActionType

    ape = AnalyticalPriceEngine()
    # Action 1: Demerger on 2023-01-01
    # Action 2: Split 2:1 (factor 0.5) on 2024-01-01
    ape.actions_by_symbol["TESTCO"] = [
        CorporateActionEvent(
            symbol="TESTCO",
            security_id="SEC_TESTCO",
            ex_date="2023-01-01",
            record_date="2023-01-01",
            effective_date="2023-01-01",
            action_type=ActionType.DEMERGER,
            action_nature=ActionNature.ENTERPRISE_ALTERING,
            factor=1.0,
            resulting_entities=[],
            source_authority="NSE",
            source_reference="REF1",
            ingestion_timestamp="2023-01-01T00:00:00Z"
        ),
        CorporateActionEvent(
            symbol="TESTCO",
            security_id="SEC_TESTCO",
            ex_date="2024-01-01",
            record_date="2024-01-01",
            effective_date="2024-01-01",
            action_type=ActionType.SPLIT,
            action_nature=ActionNature.ENTERPRISE_PRESERVING,
            factor=0.5,
            resulting_entities=[],
            source_authority="NSE",
            source_reference="REF2",
            ingestion_timestamp="2024-01-01T00:00:00Z"
        ),
    ]

    dates = ["2022-06-01", "2023-06-01", "2024-06-01"]
    df = pd.DataFrame({
        "date": dates,
        "open": [1000.0, 1000.0, 1000.0],
        "high": [1050.0, 1050.0, 1050.0],
        "low": [950.0, 950.0, 950.0],
        "close": [1000.0, 1000.0, 1000.0],
        "volume": [10000.0, 10000.0, 10000.0],
    })

    adj_df, diag = ape.derive_analytical_series("TESTCO", df, as_of_date="2024-06-01")

    # 1. History prior to demerger must be severed (2022-06-01 dropped)
    assert "2022-06-01" not in adj_df["date"].values
    assert len(adj_df) == 2

    # 2. 2023-06-01 (post-demerger but pre-split) MUST be adjusted by the 2024-01-01 split (factor 0.5)
    row_2023 = adj_df[adj_df["date"] == "2023-06-01"].iloc[0]
    assert math.isclose(row_2023["close"], 500.0, rel_tol=1e-3), f"Expected 500.0 after 2:1 split, got {row_2023['close']}"

    # 3. 2024-06-01 (post-split) remains nominal 1000.0
    row_2024 = adj_df[adj_df["date"] == "2024-06-01"].iloc[0]
    assert math.isclose(row_2024["close"], 1000.0, rel_tol=1e-3)


# ==============================================================================
# L4-DEF-03: Trade Log Export Column Name Mismatch Causing 100% NaN Prices
# ==============================================================================
def test_l4_def_03_backtest_trade_log_non_nan_prices(tmp_path):
    from core.backtest import LightweightBacktester

    tester = LightweightBacktester(base_dir=tmp_path)
    # Simulate trade record format produced in LightweightBacktester
    closed_trades = [
        {
            "trade_id": 1,
            "symbol": "TCS",
            "entry_date": "2023-01-02",
            "entry_price": 3000.0,
            "exit_date": "2023-02-01",
            "exit_price": 3300.0,
            "shares": 10,
            "gross_pnl": 3000.0,
            "net_pnl": 2950.0,
            "return_pct": 10.0,
            "exit_reason": "REBALANCE",
        }
    ]

    trade_cols = [
        "trade_id", "symbol", "entry_date", "exit_date", "entry_px", "exit_px",
        "shares", "cost_basis", "net_proceeds", "net_pnl", "return_pct", "exit_reason"
    ]
    # Testing DataFrame creation with schema columns
    trades_df = tester.build_trades_df(closed_trades, trade_cols)

    # Must NOT have NaNs in price columns
    assert not trades_df["entry_px"].isna().any(), "entry_px should not be NaN"
    assert not trades_df["exit_px"].isna().any(), "exit_px should not be NaN"
    assert math.isclose(trades_df["entry_px"].iloc[0], 3000.0)
    assert math.isclose(trades_df["exit_px"].iloc[0], 3300.0)


# ==============================================================================
# L4-DEF-04: Menchero Logarithmic Linking Premature Zeroing on Minute Active Return Spreads
# ==============================================================================
def test_l4_def_04_menchero_linking_zero_spread_preserves_attribution():
    from analytics.factor_attribution import BrinsonFachlerEngine

    engine = BrinsonFachlerEngine()
    p1 = pd.DataFrame([
        {"sector": "IT", "allocation": 0.03, "selection": 0.0, "interaction": 0.0, "total_active": 0.03, "mean_wp": 0.5, "mean_wb": 0.5},
        {"sector": "BANK", "allocation": -0.01, "selection": 0.0, "interaction": 0.0, "total_active": -0.01, "mean_wp": 0.5, "mean_wb": 0.5},
    ])
    p2 = pd.DataFrame([
        {"sector": "IT", "allocation": -0.01, "selection": 0.0, "interaction": 0.0, "total_active": -0.01, "mean_wp": 0.5, "mean_wb": 0.5},
        {"sector": "BANK", "allocation": -0.0096, "selection": 0.0, "interaction": 0.0, "total_active": -0.0096, "mean_wp": 0.5, "mean_wb": 0.5},
    ])

    df_multi = engine.link_multi_period_attributions(
        period_attributions=[p1, p2],
        portfolio_total_returns=[0.02, -0.0196078],
        benchmark_total_returns=[0.0, 0.0],
    )

    it_row = df_multi[df_multi["sector"] == "IT"].iloc[0]
    # Sector IT must NOT be zeroed out
    assert abs(it_row["allocation"]) > 1e-4, f"IT allocation should be non-zero, got {it_row['allocation']}"


# ==============================================================================
# L4-DEF-05: Date Misalignment in Risk Decomposition Regression
# ==============================================================================
def test_l4_def_05_institutional_risk_aligned_benchmark_regression():
    from analytics.institutional_risk import calculate_comprehensive_risk_suite

    dates = pd.date_range("2024-01-01", periods=50, freq="B")
    bm = pd.Series(0.01 + 0.005 * np.linspace(-1, 1, 50), index=dates)
    ret = 2.0 * bm.copy()
    ret.iloc[5] = np.nan  # Day 5 trading halt

    res = calculate_comprehensive_risk_suite(ret, benchmark_returns=bm)
    assert "beta" in res
    assert abs(res["beta"] - 2.0) < 0.1, f"Expected beta ~ 2.0, got {res['beta']}"


# ==============================================================================
# L4-DEF-07: Operational DB Schema Leaked Into Production universe.db
# ==============================================================================
def test_l4_def_07_ensure_database_schema_no_picks_history_leak(tmp_path):
    from core.data_engine import ensure_database_schema

    db_path = tmp_path / "test_universe.db"
    conn = sqlite3.connect(db_path)
    ensure_database_schema(conn)

    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [r[0] for r in cursor.fetchall()]
    conn.close()

    assert "prices" in tables
    assert "applied_corporate_actions" in tables
    # picks_history belongs strictly to operational.db, not universe.db
    assert "picks_history" not in tables, "picks_history must not be created in universe.db"


# ==============================================================================
# L4-DEF-09: FastDataCache NPZ Deserialization Stringifies NaNs
# ==============================================================================
def test_l4_def_09_fast_cache_npz_preserves_nan_semantics(tmp_path):
    from cache.fast_cache import FastDataCache

    cache = FastDataCache(cache_dir=tmp_path / "cache")
    df = pd.DataFrame({
        "symbol": ["INFY", None, "TCS", np.nan],
        "sector": [None, "IT", "IT", "TECH"],
        "price": [1500.0, 1600.0, 3200.0, np.nan]
    })

    key = "test_nan_key"
    cache.store(key, df, preferred_format="npz")
    loaded_df = cache.get(key)

    assert loaded_df is not None
    assert loaded_df["symbol"].isna().sum() == 2, "NaNs in object column must be preserved, not converted to 'nan' string"
    assert loaded_df["symbol"].iloc[1] is None or pd.isna(loaded_df["symbol"].iloc[1])
    assert str(loaded_df["symbol"].iloc[1]).lower() != "nan" or pd.isna(loaded_df["symbol"].iloc[1])


# ==============================================================================
# L4-DEF-10: Pre-Trade Compliance Weekend Boundary
# ==============================================================================
def test_l4_def_10_pretrade_audit_corporate_action_weekend_boundary(tmp_path):
    from compliance.pretrade_audit import PreTradeComplianceEngine

    audit = PreTradeComplianceEngine(base_dir=tmp_path)
    # Impending action on Monday 2026-10-19
    audit._corporate_actions = [
        {"symbol": "INFY", "ex_date": "2026-10-19", "action_type": "SPLIT"}
    ]

    actionable_df = pd.DataFrame([
        {"symbol": "INFY", "target_value": 50000.0, "sector": "IT", "adtv_30": 10.0}
    ])

    # as_of_date is Saturday 2026-10-17
    report = audit.run_pretrade_audit(
        actionable_df=actionable_df,
        as_of_date="2026-10-17",
        total_nav=1000000.0,
        available_cash=500000.0
    )

    ca_res = [r for r in report.check_results if r.check_name == "CORPORATE_ACTION_BLACKOUT_WINDOW"][0]
    # Must catch the blackout violation even on a weekend date without swallowing exception
    assert not ca_res.passed
    assert "INFY" in str(report.violations)


# ==============================================================================
# L4-DEF-11: get_latest_date Arity Acceptance
# ==============================================================================
def test_l4_def_11_get_latest_date_arity_acceptance(tmp_path):
    from core.data_engine import get_latest_date

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prices (date TEXT);")
    conn.execute("INSERT INTO prices VALUES ('2026-10-16');")
    conn.commit()
    conn.close()

    # Must accept optional db_path without raising TypeError
    latest = get_latest_date(db_path)
    assert latest == "2026-10-16"


# ==============================================================================
# L4-DEF-12: Single-Stock Benchmark Split Adjustment
# ==============================================================================
def test_l4_def_12_single_stock_benchmark_split_adjusted(tmp_path):
    from core.benchmark_validator import _load_ticker_from_db
    from core.data_engine import save_corporate_actions_registry

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    db_path = data_dir / "universe.db"

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prices (date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, symbol TEXT);")
    # Day 1: 2000, Day 2: 1000 (after 2:1 split)
    conn.execute("INSERT INTO prices VALUES ('2024-01-01', 2000.0, 2050.0, 1950.0, 2000.0, 1000, 'RELIANCE');")
    conn.execute("INSERT INTO prices VALUES ('2024-01-02', 1000.0, 1050.0, 950.0, 1000.0, 2000, 'RELIANCE');")
    conn.commit()
    conn.close()

    # Save registry with split on 2024-01-02
    actions = {
        "RELIANCE": [
            {"symbol": "RELIANCE", "ex_date": "2024-01-02", "type": "SPLIT", "factor": 0.5, "amount": 0.0}
        ]
    }
    save_corporate_actions_registry(actions, base_dir=tmp_path)

    df_bm = _load_ticker_from_db("RELIANCE", tmp_path)
    assert df_bm is not None
    # Day 1 close should be adjusted to 1000.0, preventing false -50% collapse
    assert math.isclose(df_bm["close"].iloc[0], 1000.0, rel_tol=1e-3)


# ==============================================================================
# L4-DEF-14: C99 sim_kernel MAX_UNIVERSE_SYMBOLS Boundary Initialization
# ==============================================================================
def test_l4_def_14_c99_sim_kernel_max_symbols_boundary_initialization():
    from brute_force.bridge import NativeBruteForceEngine
    import numpy as np

    engine = NativeBruteForceEngine()
    if not engine.is_available:
        pytest.skip("Native C99 kernel not available")

    # Call with N > MAX_UNIVERSE_SYMBOLS (e.g. 2500)
    # Result struct must be cleanly zeroed/initialized, never garbage
    from brute_force.cube_builder import TensorCubeContainer
    mock_cube = TensorCubeContainer(
        rebalance_indices=np.array([0, 10], dtype=np.int32),
        benchmark_regime=np.array([1, 1], dtype=np.uint8),
        sector_ids=np.zeros(2500, dtype=np.uint8),
        open_px=np.ones((20, 2500), dtype=np.float32),
        close_px=np.ones((20, 2500), dtype=np.float32),
        atr_14=np.ones((20, 2500), dtype=np.float32),
        volar_cubes=np.ones((1, 20, 2500), dtype=np.float32),
        high_cubes=np.ones((1, 20, 2500), dtype=np.float32),
        ema_cubes=np.ones((1, 20, 2500), dtype=np.float32),
        rs_pass_cubes=np.ones((1, 20, 2500), dtype=np.uint8),
        symbols=[f"S{i}" for i in range(2500)],
        dates=["2024-01-01"] * 20,
        lookback_values=[252],
        ema_span_values=[200],
    )

    params = [{
        "param_id": 999,
        "schedule_idx": 0,
        "top_n": 10,
        "start_date_idx": 0,
        "end_date_idx": 19,
    }]

    res_df = engine.run_sweep(mock_cube, params)
    assert not res_df.empty
    # Must report -99.9 or 0.0, never garbage e.g. 1e30
    assert res_df["sharpe"].iloc[0] <= 0.0
    assert abs(res_df["sharpe"].iloc[0]) < 1000.0


# ==============================================================================
# L4-DEF-15: Dangling Pointer Risk in _as_contiguous_ptr
# ==============================================================================
def test_l4_def_15_as_contiguous_ptr_pins_array_reference():
    import gc
    from brute_force.bridge import _as_contiguous_ptr

    # Non-contiguous array slice
    non_contig = np.arange(100, dtype=np.float32)[::2]
    ptr, pinned_obj = _as_contiguous_ptr(non_contig, np.float32)

    assert ptr != 0
    assert pinned_obj is not None
    # Verify pinned_obj keeps memory valid after gc
    gc.collect()
    assert pinned_obj.ctypes.data == ptr


# ==============================================================================
# L4-DEF-17: Telegram Bot HTML Entity Escaping on Ampersand
# ==============================================================================
def test_l4_def_17_telegram_html_escaped_for_ampersand():
    from core.telegram_sender import format_telegram_alert

    sample_picks = pd.DataFrame([{
        "rank": 1,
        "symbol": "ONGC",
        "sector": "OIL & GAS",
        "close": 280.0,
        "atr_14": 5.0,
        "stop_loss": 265.0,
        "volar_score": 5.5,
        "reason_code": "PASS",
        "ret_1y": 45.0,
        "high_252": 300.0,
        "ema_200": 250.0,
    }])

    regime = {"label": "BULL", "status": "BULL", "bm_close": 24000.0, "bm_ema20": 23500.0}
    msg = format_telegram_alert(sample_picks, as_of_date="2026-10-16", regime_info=regime)

    # Ampersand in "OIL & GAS" must be escaped to &amp;
    assert "OIL &amp; GAS" in msg, "Ampersands in HTML formatted Telegram messages must be escaped"
    assert "OIL & GAS" not in msg.replace("OIL &amp; GAS", "")


# ==============================================================================
# L4-DEF-18: Telegram Message Chunking Maintains Tag Closure
# ==============================================================================
def test_l4_def_18_telegram_chunking_maintains_html_tag_closure():
    from core.telegram_sender import _chunk_message

    # Construct a message inside <pre> that spans > 4000 chars
    lines = ["<pre>"] + [f"Line {i:04d}: Security XYZ Momentum Score" for i in range(150)] + ["</pre>"]
    long_msg = "\n".join(lines)
    assert len(long_msg) > 4000

    chunks = _chunk_message(long_msg, max_length=2000)
    assert len(chunks) > 1

    for i, c in enumerate(chunks):
        # Open tags must be closed within each chunk
        assert c.count("<pre>") == c.count("</pre>"), f"Chunk {i} has unclosed <pre> tag"


# ==============================================================================
# L4-DEF-19: In-Place Decompression Return Size Inversion
# ==============================================================================
def test_l4_def_19_cloud_sync_decompress_file_in_place_stats(tmp_path):
    from scripts.cloud_sync import decompress_file

    raw_data = b"MIP_DATABASE_RAW_BYTES_" * 100000  # ~2.3 MB
    target_path = tmp_path / "universe.db"

    # Compress into target_path
    with gzip.open(target_path, "wb") as f_out:
        f_out.write(raw_data)

    gz_actual_size = target_path.stat().st_size
    raw_actual_size = len(raw_data)
    assert gz_actual_size < raw_actual_size

    # Decompress in-place: decompress_file(target_path, target_path)
    gz_reported, raw_reported = decompress_file(target_path, target_path)

    assert gz_reported == gz_actual_size, f"Expected gz_size {gz_actual_size}, got {gz_reported}"
    assert raw_reported == raw_actual_size, f"Expected raw_size {raw_actual_size}, got {raw_reported}"


# ==============================================================================
# L4-DEF-06: Incremental Budget Allocation for Retained HOLD Positions
# ==============================================================================
def test_l4_def_06_avail_for_buys_retained_holdings_incremental_budget(tmp_path):
    from core.portfolio import PortfolioManager
    from core.scanner import ScannerReasonCode

    pm = PortfolioManager(base_dir=tmp_path)
    # Scenario: 1 existing holding worth 50k, 100k capital, 50k cash.
    # New entrant wants 40k. Should NOT be starved to zero.
    current_holdings = {"TCS": 10}
    screener_df = pd.DataFrame([
        {"symbol": "TCS", "close": 5000.0, "sector": "IT", "volar_score": 5.0, "rank": 1, "high_252": 5200.0, "ema_200": 4500.0, "reason_code": "PASS", "allow_buy": True, "corporate_action_status": "CLEAN"},
        {"symbol": "INFY", "close": 1500.0, "sector": "IT", "volar_score": 4.5, "rank": 2, "high_252": 1600.0, "ema_200": 1300.0, "reason_code": "PASS", "allow_buy": True, "corporate_action_status": "CLEAN"},
    ])
    prices = {"TCS": 5000.0, "INFY": 1500.0}

    orders = pm.generate_rebalance_orders(
        current_holdings=current_holdings,
        screener_df=screener_df,
        capital=100000.0,
        cash=50000.0,
        top_n=2,
        exit_buffer_rank=40,
        prices=prices,
        allow_research_overrides=True,
        regime_active=False,
    )

    buy_infy = orders[orders["symbol"] == "INFY"]
    assert not buy_infy.empty, "INFY should receive a BUY order"
    assert buy_infy.iloc[0]["target_shares"] > 0, "INFY should receive positive shares"


# ==============================================================================
# L4-DEF-08: AutoFetch Fails Closed if Universe Current but Benchmark Fails
# ==============================================================================
def test_l4_def_08_auto_fetch_current_fails_closed_if_benchmark_sync_fails(tmp_path, monkeypatch):
    from core.auto_fetch import PydroidAutoFetch, AutoFetchStatus

    fetcher = PydroidAutoFetch(base_dir=tmp_path)
    # Mock no missing dates for universe
    monkeypatch.setattr(fetcher, "get_missing_trading_dates", lambda target_date=None: [])
    # Mock failing benchmark sync
    monkeypatch.setattr(fetcher, "sync_benchmark", lambda: {"status": "FAILED", "message": "API timeout"})

    # Setup dummy prices table with 1 date
    db_path = tmp_path / "data" / "universe.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prices (date TEXT);")
    conn.execute("INSERT INTO prices VALUES ('2026-10-16');")
    conn.commit()
    conn.close()

    res = fetcher.sync_universe(target_date="2026-10-16")
    # Must fail closed, not report CURRENT
    assert res["status"] == AutoFetchStatus.VALIDATION_FAILURE.value
    assert "benchmark sync failed" in res["message"].lower()


# ==============================================================================
# L4-DEF-13: Synthetic Universe Proxy Clamps Constituent Split Dislocation
# ==============================================================================
def test_l4_def_13_synthetic_universe_proxy_clamps_constituent_returns(tmp_path):
    from core.benchmark_validator import _build_universe_proxy_series

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "universe.db"

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prices (date TEXT, symbol TEXT, close REAL);")

    # Insert 60 symbols with >1000 rows, one has a 10:1 split (-90% drop)
    dates = [f"2024-01-{i:02d}" for i in range(1, 20)]
    for s_idx in range(60):
        sym = f"SYM{s_idx:02d}"
        for d in dates:
            px = 1000.0
            if sym == "SYM00" and d >= "2024-01-10":
                px = 100.0  # -90% drop
            conn.execute("INSERT INTO prices VALUES (?, ?, ?);", (d, sym, px))
    conn.commit()
    conn.close()

    proxy_df = _build_universe_proxy_series(base_dir=tmp_path)
    assert proxy_df is not None and not proxy_df.empty
    # The proxy series index must not collapse by 90%
    day9_px = proxy_df[proxy_df["date"] == "2024-01-09"]["close"].iloc[0]
    day10_px = proxy_df[proxy_df["date"] == "2024-01-10"]["close"].iloc[0]
    ret = (day10_px / day9_px) - 1.0
    assert abs(ret) < 0.10, f"Expected stable median return, got {ret}"


# ==============================================================================
# L4-DEF-16: Tensor Cube Builder Applies Analytical Corporate Action Adjustments
# ==============================================================================
def test_l4_def_16_cube_builder_applies_analytical_corporate_actions(tmp_path):
    from brute_force.cube_builder import build_tensor_cube
    from core.data_engine import save_corporate_actions_registry

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "universe.db"

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE prices (date TEXT, symbol TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL);")
    # Day 1: 2000, Day 2: 1000 (after 2:1 split)
    conn.execute("INSERT INTO prices VALUES ('2024-01-01', 'RELIANCE', 2000.0, 2050.0, 1950.0, 2000.0, 1000);")
    conn.execute("INSERT INTO prices VALUES ('2024-01-02', 'RELIANCE', 1000.0, 1050.0, 950.0, 1000.0, 2000);")
    conn.commit()
    conn.close()

    actions = {
        "RELIANCE": [
            {"symbol": "RELIANCE", "ex_date": "2024-01-02", "type": "SPLIT", "factor": 0.5, "amount": 0.0}
        ]
    }
    save_corporate_actions_registry(actions, base_dir=tmp_path)

    # Build benchmark file in tmp_path
    b_df = pd.DataFrame({
        "date": ["2024-01-01", "2024-01-02"],
        "close": [20000.0, 20100.0],
        "ema_20": [19900.0, 20000.0],
        "is_healthy": [True, True]
    })
    b_df.to_csv(data_dir / "benchmark_nifty500.csv", index=False)

    cube = build_tensor_cube(
        universe_name="TEST_UNI",
        start_date="2024-01-01",
        end_date="2024-01-02",
        base_dir=tmp_path,
        symbols=["RELIANCE"],
    )

    # In the resulting cube close_px matrix, Day 1 close should be adjusted to 1000.0
    rel_idx = cube.symbols.index("RELIANCE")
    assert math.isclose(cube.close_px[0, rel_idx], 1000.0, rel_tol=1e-3), f"Expected adjusted close 1000.0, got {cube.close_px[0, rel_idx]}"
