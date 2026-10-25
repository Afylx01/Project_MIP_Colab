"""Point-in-time membership contracts for the native C kernel and resolver."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.cube_builder import TensorCubeContainer
from brute_force.bridge import NativeBruteForceEngine


def _cube(membership_mask):
    num_dates, n = 12, 2
    dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
    symbols = ["A", "B"]
    px = np.zeros((num_dates, n), dtype=np.float32)
    for t in range(num_dates):
        px[t, 0] = 100.0 + t
        px[t, 1] = 100.0 + t if t <= 6 else (100.0 + 6) * (1.10 ** (t - 6))
    reb = np.array([0, 6], dtype=np.int32)
    sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
    return TensorCubeContainer(
        dates=dates,
        symbols=symbols,
        schedule_indices_map=sched,
        open_px=px,
        close_px=px,
        atr_14=np.ones((num_dates, n), dtype=np.float32),
        volar_cubes=np.ones((1, num_dates, n), dtype=np.float32),
        high_cubes=np.ones((1, num_dates, n), dtype=np.float32),
        ema_cubes=np.ones((1, num_dates, n), dtype=np.float32),
        rs_pass_cubes=np.ones((1, num_dates, n), dtype=np.uint8),
        valid_price_mask=np.ones((num_dates, n), dtype=np.uint8),
        lookback_values=[63, 126, 252, 504],
        ema_span_values=[20, 50, 100, 150, 200],
        universe_membership_mask=membership_mask,
    )


def _param():
    return {
        "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 11,
        "lookback_idx": 0, "ema_idx": 0, "top_n": 1, "exit_buffer_rank": 40,
        "max_per_sector": 99, "sizing_mode": "equal_weight", "filter_flags": 0,
        "initial_capital": 100_000.0, "friction_bps": 0.0, "slippage_bps": 0.0,
    }


def test_kernel_blocks_non_members_and_forces_index_removal():
    engine = NativeBruteForceEngine(force_recompile=False)
    # A is a member only before the second rebalance; B only on/after it.
    mask = np.zeros((12, 2), dtype=np.uint8)
    mask[:6, 0] = 1
    mask[6:, 1] = 1

    with_mask = engine.execute_sweep([_param()], _cube(mask), num_threads=1)[0]
    without_mask = engine.execute_sweep([_param()], _cube(None), num_threads=1)[0]

    # With PIT: A is bought, then removed and sold at the second rebalance (1
    # closed trade); B is then bought and held. Without the mask, A is retained
    # (0 closed trades) and B is never bought.
    assert int(with_mask["total_trades"]) == 1
    assert int(without_mask["total_trades"]) == 0
    assert float(with_mask["ending_equity"]) > float(without_mask["ending_equity"]) * 1.2


def test_snapshot_pit_includes_long_tenured_members():
    from core.pit_membership import members_db_as_of
    m = members_db_as_of("NIFTY500", "2018-12-28", PROJECT_ROOT)
    # NSE's 2018-10-04 published list (Internet Archive anchor) contains ABB,
    # RELIANCE and HDFCBANK. ADANIENT was excluded on 2018-04-02 and only
    # re-included on 2020-09-25 per the NSE press releases, so it must NOT be
    # a NIFTY 500 member at the end of 2018 — the old niftyhistory table had
    # this backwards.
    assert "ABB" in m
    assert "RELIANCE" in m
    assert "HDFCBANK" in m
    assert "ADANIENT" not in m


def test_snapshot_pit_is_empty_before_first_snapshot():
    from core.pit_membership import members_db_as_of
    assert members_db_as_of("NIFTY500", "2015-12-31", PROJECT_ROOT) == set()


def test_snapshot_pit_applies_effective_date():
    from core.pit_membership import members_db_as_of
    sep = members_db_as_of("NIFTY500", "2018-09-28", PROJECT_ROOT)
    dec = members_db_as_of("NIFTY500", "2018-12-28", PROJECT_ROOT)
    # 2018-12-28 event: ADANIGREEN/FORTIS/RITES in, BHARATFIN out.
    assert "ADANIGREEN" not in sep and "ADANIGREEN" in dec
    assert "BHARATFIN" in sep and "BHARATFIN" not in dec
