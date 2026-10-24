"""Contracts for the unbiased historical-universe policy.

The scanner is allowed to use the latest constituents (live decisions).
Historical backtests and brute force resolve named indices from their PIT
tables; indices without a PIT table are refused, and under-covered windows
are refused by a breadth gate.
"""
import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.universe_policy import (
    MIN_ELIGIBLE_SYMBOLS,
    UniversePolicyError,
    all_db_symbols,
    check_breadth,
    resolve_universe,
)
from core.backtest import LightweightBacktester
from brute_force.cube_builder import build_tensor_cube
from brute_force.runner import BruteForceCampaignRunner


def test_unknown_index_refused_by_backtester():
    bt = LightweightBacktester(PROJECT_ROOT)
    with pytest.raises(UniversePolicyError, match="INDEX_UNIVERSE_REQUIRES_POINT_IN_TIME"):
        bt.run(start_date="2016-01-01", end_date="2016-03-31", universe_mode="NIFTY_NOT_REAL")


def test_unknown_index_refused_by_cube():
    with pytest.raises(UniversePolicyError, match="INDEX_UNIVERSE_REQUIRES_POINT_IN_TIME"):
        build_tensor_cube(universe_name="NIFTY_NOT_REAL", start_date="2016-01-01", end_date="2016-06-30")


def test_nifty500_uses_point_in_time_membership():
    p = resolve_universe("NIFTY500", "2018-01-01", PROJECT_ROOT, end_date="2026-08-31")
    assert p["source"] == "PIT_SNAPSHOT"
    assert p["pit_index"] == "NIFTY500"
    assert p["survivorship_bias_risk"] is False
    assert len(p["symbols"]) > 400


def test_nifty500_2016_refused_by_pit_breadth():
    bt = LightweightBacktester(PROJECT_ROOT)
    with pytest.raises(ValueError, match="INSUFFICIENT_PIT_BREADTH"):
        bt.run(start_date="2016-01-01", end_date="2016-12-31", universe_mode="NIFTY500")


def test_2017_has_enough_pit_breadth_while_2016_start_has_none():
    from core.pit_membership import coverage_stats

    s17 = coverage_stats("NIFTY500", "2017-01-01", base_dir=PROJECT_ROOT)
    assert s17["db_symbols_mapped"] == 375
    assert s17["eligible_symbols"] == 306
    assert s17["eligible_symbols"] >= MIN_ELIGIBLE_SYMBOLS
    # No snapshot exists on/before 2016-01-01, so a start there is refused.
    s16 = coverage_stats("NIFTY500", "2016-01-01", base_dir=PROJECT_ROOT)
    assert s16["db_symbols_mapped"] == 0
    assert s16["eligible_symbols"] == 0


def test_all_is_full_cross_section_and_not_survivorship_selected():
    p = resolve_universe("ALL", "2016-01-01", PROJECT_ROOT)
    assert p["source"] == "FULL_CROSS_SECTION"
    assert p["symbols"] is None
    assert p["survivorship_bias_risk"] is False
    assert p["data_completeness_risk"] is True


def test_explicit_symbols_are_a_deliberate_universe():
    p = resolve_universe("RESEARCH", "2016-01-01", PROJECT_ROOT, explicit_symbols=["AAA", "BBB"])
    assert p["source"] == "EXPLICIT_SYMBOLS"
    assert p["symbols"] == ["AAA", "BBB"]


def test_pit_membership_takes_priority_over_current_fixture_flag():
    # The old test-only current-list path must not override real PIT data.
    p = resolve_universe(
        "NIFTY500", "2018-01-01", PROJECT_ROOT,
        end_date="2026-08-31", allow_current_constituents=True,
    )
    assert p["source"] == "PIT_SNAPSHOT"
    assert p["survivorship_bias_risk"] is False


def test_breadth_gate_refuses_thin_windows():
    with pytest.raises(UniversePolicyError, match="INSUFFICIENT_UNIVERSE_BREADTH"):
        check_breadth(MIN_ELIGIBLE_SYMBOLS - 1, "FULL_CROSS_SECTION")
    check_breadth(MIN_ELIGIBLE_SYMBOLS, "FULL_CROSS_SECTION")
    # Explicit research universes are deliberate fixtures and are not gated.
    check_breadth(1, "EXPLICIT_SYMBOLS")


def test_backtester_refuses_2008_thin_window():
    bt = LightweightBacktester(PROJECT_ROOT)
    with pytest.raises(UniversePolicyError, match="INSUFFICIENT_UNIVERSE_BREADTH"):
        bt.run(start_date="2008-01-01", end_date="2008-12-31", universe_mode="ALL")


def test_all_universe_includes_delisted_names():
    symbols = all_db_symbols(PROJECT_ROOT)
    con = sqlite3.connect(f"file:{PROJECT_ROOT/'data'/'universe.db'}?mode=ro", uri=True)
    dead = con.execute(
        "SELECT symbol FROM prices GROUP BY symbol HAVING MAX(date) < '2026-09-01' LIMIT 1"
    ).fetchone()
    con.close()
    assert dead is not None, "test requires at least one dead symbol"
    assert dead[0] in symbols


def test_live_scanner_loader_still_returns_latest_constituents():
    from core.data_engine import load_universe_constituents

    syms = load_universe_constituents("NIFTY500")
    assert len(syms) > 400, "the scanner must still resolve the latest NIFTY500 list"


def test_runner_defaults_cube_universe_to_all():
    sig = inspect.signature(BruteForceCampaignRunner.ensure_cube)
    assert sig.parameters["universe_name"].default == "ALL"
    sig = inspect.signature(BruteForceCampaignRunner.run_custom_backtest)
    # None means "use the existing cube, else ALL" — never implicitly an index.
    assert sig.parameters["universe_name"].default is None
