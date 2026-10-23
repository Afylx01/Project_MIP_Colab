"""
tests/test_fixes_2026_10_23.py - Regression contracts for the codebase audit fixes.

Covers:
  FIX-01  picks_history schema migration (silent INSERT failure)
  FIX-02  cache rejects entries larger than the configured budget
  FIX-03  Telegram chunker hard-splits long lines and stays under the limit
  FIX-04  backtester filters non-session dates and defers placeholder-bar fills
  FIX-05  backtester exposes universe/PIT metadata and strict PIT mode
  FIX-06  delisting resolved from last observed bar, not stale flags
  FIX-07  standalone sector rotation computes RRG instead of defaulting to 100/100
  FIX-08  CLI exposes menu-numbered dispatch
"""

import sqlite3
import sys
import tempfile
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.scanner import PICKS_HISTORY_SCHEMA, ensure_picks_history_schema
from core.telegram_sender import _chunk_message
from cache.fast_cache import FastDataCache


def test_fix01_picks_history_schema_migrates_legacy_table():
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE picks_history (
            pick_date TEXT, symbol TEXT, rank INTEGER, industry TEXT, regime TEXT,
            signal_type TEXT, status TEXT, entry_price REAL, ret_1w REAL, ret_1m REAL,
            ret_3m REAL, ret_6m REAL, ret_1y REAL, exit_date TEXT, exit_price REAL,
            exit_reason TEXT
        )
    """)
    ensure_picks_history_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(picks_history)")}
    assert set(PICKS_HISTORY_SCHEMA).issubset(cols)
    conn.execute(
        "INSERT OR REPLACE INTO picks_history "
        "(pick_date, symbol, rank, industry, regime, signal_type, status, entry_price, "
        "ret_1w, ret_1m, ret_since, last_px_date, volar_score) "
        "VALUES ('2026-10-19','TEST',1,'IT','BULL','BUY','ACTIVE',100.0,NULL,NULL,0.0,'2026-10-19',2.5)"
    )
    assert conn.execute("SELECT COUNT(*) FROM picks_history").fetchone()[0] == 1
    conn.close()


def test_fix02_cache_rejects_oversized_entry():
    tmp = Path(tempfile.mkdtemp(prefix="mip_cache_fix_"))
    try:
        cache = FastDataCache(cache_dir=tmp, max_cache_size_mb=1)
        assert cache.store("small", pd.DataFrame({"a": [1, 2, 3]})) is True
        big = pd.DataFrame(np.random.default_rng(1).random((60000, 4)), columns=list("abcd"))
        assert cache.store("big", big) is False
        assert not (tmp / "big.npz").exists()
        assert cache.get("small") is not None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_fix03_chunker_splits_long_lines_under_limit():
    msg = "A" * 9500
    chunks = _chunk_message(msg, max_length=4000)
    assert len(chunks) > 1
    assert all(len(c) <= 4000 for c in chunks)
    assert "".join(chunks) == msg

    pre = "<pre>" + ("B" * 9000) + "</pre>"
    pre_chunks = _chunk_message(pre, max_length=4000)
    assert all(len(c) <= 4000 for c in pre_chunks)
    assert pre_chunks[0].startswith("<pre>")
    assert "</pre>" not in pre_chunks[0] or pre_chunks[0].endswith("</pre>")


@pytest.mark.integration
def test_fix04_05_06_backtester_metadata_calendar_and_delisting():
    from core.backtest import LightweightBacktester
    from core.data_engine import load_trading_calendar

    out = Path(tempfile.mkdtemp(prefix="mip_bt_fix_"))
    try:
        bt = LightweightBacktester(PROJECT_ROOT, output_dir=out)
        res = bt.run(start_date="2026-05-01", end_date="2026-08-31", top_n=10, exit_buffer=20)
        assert res["universe_mode"] == "ALL"
        assert res["universe_size"] > 0
        assert res["calendar_filtered_dates"] >= 1
        assert res["deferred_fills"] >= 0
        assert res["survivorship_bias_risk"] is False

        calendar = set(load_trading_calendar(cal_path=PROJECT_ROOT / "data" / "trading_calendar.txt"))
        trade_log = pd.read_csv(out / "trade_log.csv")
        assert "2026-05-01" not in set(trade_log.get("entry_date", []))
        assert "2026-05-01" not in set(trade_log.get("exit_date", []))
        if not trade_log.empty:
            assert set(trade_log["entry_date"]).issubset(calendar | {"2026-05-01"})

        # ABAN still quotes through 2026-10-19; the stale flag must not mark it delisted.
        assert "ABAN" not in bt.delisted_symbols
        assert "RCOM" not in bt.delisted_symbols
    finally:
        shutil.rmtree(out, ignore_errors=True)


def test_fix05_strict_point_in_time_raises():
    from core.backtest import LightweightBacktester

    bt = LightweightBacktester(PROJECT_ROOT)
    with pytest.raises(ValueError, match="NO_POINT_IN_TIME_SNAPSHOT"):
        bt.run(start_date="2026-01-01", end_date="2026-08-31", top_n=5,
               universe_mode="NIFTY500", strict_point_in_time=True)


@pytest.mark.integration
def test_fix07_standalone_sector_rotation_computes_rrg():
    from core.sector_rotation import SectorRotationEngine

    engine = SectorRotationEngine(PROJECT_ROOT)
    result = engine.compute_sector_rotation(as_of_date="2026-10-19")
    sectors = result.get("sectors", [])
    assert len(sectors) > 5
    ratios = [s.get("rrg_rs_ratio", 100.0) for s in sectors]
    moments = [s.get("rrg_rs_momentum", 100.0) for s in sectors]
    assert any(abs(v - 100.0) > 1e-6 for v in ratios), "RRG ratios must not be defaulted"
    assert any(abs(v - 100.0) > 1e-6 for v in moments), "RRG momentum must not be defaulted"
    assert len({s.get("rrg_quadrant") for s in sectors}) >= 2


def test_fix08_cli_menu_option_parser():
    import main

    parser = main.build_parser()
    args = parser.parse_args(["--menu-option", "12"])
    assert args.menu_option == 12
    assert "Headless --option map" in (parser.epilog or "")
