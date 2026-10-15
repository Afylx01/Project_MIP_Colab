"""
grid.py - Parameter Space & Multi-Tier Matrix Generators for Project MIP
Supports Snapdragon 8 Gen 2 C99 NEON Brute Force Optimization.
"""

from typing import List, Dict, Any, Tuple
import itertools
import random
import numpy as np

# Canonical Values
LOOKBACK_VALUES = [126, 189, 252, 315]  # Index 0, 1, 2, 3 (Canonical 252 is idx 2)
EMA_SPAN_VALUES = [50, 100, 150, 200, 250] # Index 0, 1, 2, 3, 4 (Canonical 200 is idx 3)

# Filter Bitmasks matching sim_kernel.c & bridge.py
FILTER_RETRACE       = (1 << 0) # 0x01
FILTER_TREND         = (1 << 1) # 0x02
FILTER_RS            = (1 << 2) # 0x04
FILTER_REGIME        = (1 << 3) # 0x08
FILTER_SECTOR_CAP    = (1 << 4) # 0x10
FILTER_RESIDUAL_MOM  = (1 << 5) # 0x20
FILTER_VOL_TARGETING = (1 << 6) # 0x40
FILTER_DELIVERY_VETO = (1 << 7) # 0x80

CANONICAL_FILTER_FLAGS = FILTER_RETRACE | FILTER_TREND | FILTER_RS | FILTER_REGIME | FILTER_SECTOR_CAP
NEXTGEN_ALL_FLAGS = CANONICAL_FILTER_FLAGS | FILTER_RESIDUAL_MOM | FILTER_VOL_TARGETING | FILTER_DELIVERY_VETO

# Rebalance Schedule Indices
SCHEDULE_MAP = {
    "weekly": 0,
    "monthly": 1,
    "quarterly": 2,
    "half_yearly": 3,
    "yearly": 4,
}

# Historical Macro Eras
MACRO_ERAS = {
    "2010-2013": ("2010-01-01", "2013-12-31", "Post-GFC / Euro Sovereign Debt Consolidation"),
    "2011-2021": ("2011-01-01", "2021-12-31", "10-Year Secular Bull Market"),
    "2010-2016": ("2010-01-01", "2016-12-31", "Policy Paralysis to Modi Election & Demonetization"),
    "2012-2018": ("2012-01-01", "2018-12-31", "Midcap & Smallcap Supercycle"),
    "2016-2026": ("2016-01-01", "2026-08-31", "Modern 10-Year Post-Demonetization Regime"),
    "2020-2021": ("2020-01-01", "2021-12-31", "Covid Shock & Rapid Recovery Crisis Alpha"),
    "2008-2026": ("2008-01-01", "2026-10-09", "Full 18-Year Complete Historical Cycle"),
}

TOP_N_GRID = [5, 10, 15, 20]
REBALANCE_SCHEDULES = ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]

CANONICAL_BASELINE = {
    "param_id": 0,
    "schedule": "monthly",
    "schedule_idx": 1,
    "start_date": "2016-01-01",
    "end_date": "2026-08-31",
    "start_date_idx": 0,
    "end_date_idx": 0,
    "lookback": 252,
    "lookback_idx": 2,  # index in LOOKBACK_VALUES
    "ema_trend": 200,
    "ema_idx": 3,       # index in EMA_SPAN_VALUES
    "retrace_threshold": 0.80,
    "top_n": 20,
    "exit_buffer_rank": 40,
    "max_per_sector": 2,
    "sizing_mode": "atr_risk_parity",
    "filter_flags": CANONICAL_FILTER_FLAGS,
    "initial_capital": 1_000_000.0,
    "friction_bps": 15.0,
    "slippage_bps": 5.0,
    "risk_per_trade_pct": 1.0,
}


def get_canonical_baseline_param() -> Dict[str, Any]:
    return CANONICAL_BASELINE.copy()


def generate_tier1_baseline_matrix(cube) -> List[Dict[str, Any]]:
    """
    Tier 1: Canonical Baseline across 7 Macro Eras x 5 Rebalance Schedules = 35 runs.
    """
    grid = []
    pid = 0
    for era_key, (start_dt, end_dt, era_name) in MACRO_ERAS.items():
        s_idx = cube.date_to_idx.get(start_dt, 0)
        # find closest available start date
        if start_dt not in cube.date_to_idx:
            avail = [cube.date_to_idx[d] for d in cube.dates if d >= start_dt]
            s_idx = min(avail) if avail else 0

        # find closest available end date
        e_idx = cube.date_to_idx.get(end_dt, cube.num_dates - 1)
        if end_dt not in cube.date_to_idx:
            avail = [cube.date_to_idx[d] for d in cube.dates if d <= end_dt]
            e_idx = max(avail) if avail else (cube.num_dates - 1)

        for sched_name in REBALANCE_SCHEDULES:
            p = CANONICAL_BASELINE.copy()
            p["param_id"] = pid
            p["tier"] = "TIER_1_BASELINE"
            p["era"] = era_key
            p["era_description"] = era_name
            p["schedule"] = sched_name
            p["schedule_idx"] = SCHEDULE_MAP[sched_name]
            p["start_date"] = start_dt
            p["end_date"] = end_dt
            p["start_date_idx"] = s_idx
            p["end_date_idx"] = e_idx
            grid.append(p)
            pid += 1
    return grid


def generate_tier2_ablation_grid(cube) -> List[Dict[str, Any]]:
    """
    Tier 2: Systematic Filter Ablation (Leave-One-Out) on Full History & Modern Regime.
    11 variants x 2 Eras x 2 Schedules (Monthly, Weekly) = 44 runs.
    """
    ablation_specs = [
        ("CANONICAL_ALL_ON", CANONICAL_FILTER_FLAGS, "atr_risk_parity", "Baseline with all 5 core filters active"),
        ("RETRACE_OFF", CANONICAL_FILTER_FLAGS & ~FILTER_RETRACE, "atr_risk_parity", "Retrace filter disabled"),
        ("TREND_EMA_OFF", CANONICAL_FILTER_FLAGS & ~FILTER_TREND, "atr_risk_parity", "200 EMA trend filter disabled"),
        ("RS_FILTER_OFF", CANONICAL_FILTER_FLAGS & ~FILTER_RS, "atr_risk_parity", "Relative Strength filter disabled"),
        ("REGIME_FILTER_OFF", CANONICAL_FILTER_FLAGS & ~FILTER_REGIME, "atr_risk_parity", "Benchmark Regime filter disabled"),
        ("SECTOR_CAP_OFF", CANONICAL_FILTER_FLAGS & ~FILTER_SECTOR_CAP, "atr_risk_parity", "Sector concentration cap disabled"),
        ("SIZING_EQUAL_WEIGHT", CANONICAL_FILTER_FLAGS, "equal_weight", "Equal weight (1/N) position sizing"),
        ("RESIDUAL_MOMENTUM_ON", CANONICAL_FILTER_FLAGS | FILTER_RESIDUAL_MOM, "atr_risk_parity", "Idiosyncratic Residual Momentum active"),
        ("VOL_TARGETING_ON", CANONICAL_FILTER_FLAGS | FILTER_VOL_TARGETING, "atr_risk_parity", "Volatility Targeting Cash Shield active"),
        ("DELIVERY_VETO_ON", CANONICAL_FILTER_FLAGS | FILTER_DELIVERY_VETO, "atr_risk_parity", "Delivery Microstructure Veto active"),
        ("NEXTGEN_ALL_COMBINED", NEXTGEN_ALL_FLAGS, "atr_risk_parity", "All Next-Gen Features 1-4 active"),
    ]

    target_eras = ["2008-2026", "2016-2026"]
    target_schedules = ["monthly", "weekly"]

    grid = []
    pid = 0
    for era_key in target_eras:
        start_dt, end_dt, era_name = MACRO_ERAS[era_key]
        s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_dt], default=0)
        e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= end_dt], default=cube.num_dates - 1)

        for sched_name in target_schedules:
            for spec_name, flags, sizing, desc in ablation_specs:
                p = CANONICAL_BASELINE.copy()
                p["param_id"] = pid
                p["tier"] = "TIER_2_ABLATION"
                p["ablation_variant"] = spec_name
                p["variant_desc"] = desc
                p["era"] = era_key
                p["era_description"] = era_name
                p["schedule"] = sched_name
                p["schedule_idx"] = SCHEDULE_MAP[sched_name]
                p["start_date"] = start_dt
                p["end_date"] = end_dt
                p["start_date_idx"] = s_idx
                p["end_date_idx"] = e_idx
                p["filter_flags"] = flags
                p["sizing_mode"] = sizing
                if spec_name == "SECTOR_CAP_OFF":
                    p["max_per_sector"] = 99
                grid.append(p)
                pid += 1
    return grid


def generate_tier3_hyperparameter_grid(
    cube,
    era_key: str = "2008-2026",
    schedules: List[str] = None,
    sample_size: int = 128000,
) -> List[Dict[str, Any]]:
    """
    Tier 3: Factorial Hyperparameter Grid across Top N, Lookbacks, EMAs, Buffers, Retrace, Sector Caps.
    Produces institutional parameter sensitivity maps.
    """
    if schedules is None:
        schedules = ["monthly", "quarterly", "weekly"]

    start_dt, end_dt, era_name = MACRO_ERAS[era_key]
    s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_dt], default=0)
    e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= end_dt], default=cube.num_dates - 1)

    top_n_opts = [5, 10, 15, 20]
    lookback_opts = list(range(len(LOOKBACK_VALUES)))  # 0, 1, 2, 3
    ema_opts = list(range(len(EMA_SPAN_VALUES)))       # 0, 1, 2, 3, 4
    buffer_opts = [10, 20, 30, 40]
    retrace_opts = [0.70, 0.75, 0.80, 0.85]
    sector_opts = [1, 2, 3, 99]
    sizing_opts = ["atr_risk_parity", "equal_weight"]

    full_combos = list(itertools.product(
        schedules, top_n_opts, lookback_opts, ema_opts, buffer_opts, retrace_opts, sector_opts, sizing_opts
    ))

    # If full_combos exceeds sample_size, take random sample; else take all or cycle with jitter
    if len(full_combos) > sample_size:
        random.seed(42)
        combos = random.sample(full_combos, sample_size)
    else:
        combos = full_combos

    grid = []
    for pid, (sched, tn, lb_idx, ema_idx, buf, ret, sec, sz) in enumerate(combos):
        p = CANONICAL_BASELINE.copy()
        p["param_id"] = pid
        p["tier"] = "TIER_3_GRID"
        p["era"] = era_key
        p["schedule"] = sched
        p["schedule_idx"] = SCHEDULE_MAP[sched]
        p["start_date"] = start_dt
        p["end_date"] = end_dt
        p["start_date_idx"] = s_idx
        p["end_date_idx"] = e_idx
        p["top_n"] = tn
        p["lookback_idx"] = lb_idx
        p["lookback"] = LOOKBACK_VALUES[lb_idx]
        p["ema_idx"] = ema_idx
        p["ema_trend"] = EMA_SPAN_VALUES[ema_idx]
        p["exit_buffer_rank"] = buf
        p["retrace_threshold"] = ret
        p["max_per_sector"] = sec
        p["sizing_mode"] = sz
        grid.append(p)
    return grid


def generate_tier4_rolling_windows_grid(
    cube,
    num_windows: int = 500,
    window_lengths_years: List[int] = None,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Tier 4: Monte Carlo Rolling Windows for statistical validation and Deflated Sharpe Ratio (DSR).
    Samples random sub-periods of 1y, 3y, 5y, 7y, 10y across 2008-2026.
    """
    if window_lengths_years is None:
        window_lengths_years = [1, 3, 5, 7, 10]

    random.seed(seed)
    T = cube.num_dates

    # Minimum start after warmup (bar 350)
    min_start_idx = 350
    grid = []
    pid = 0

    windows_per_len = num_windows // len(window_lengths_years)

    for y_len in window_lengths_years:
        bars_len = int(y_len * 252)
        max_start = T - bars_len - 10
        if max_start <= min_start_idx:
            continue

        for _ in range(windows_per_len):
            s_idx = random.randint(min_start_idx, max_start)
            e_idx = s_idx + bars_len

            start_dt = cube.dates[s_idx]
            end_dt = cube.dates[e_idx]

            # Canonical Baseline variant
            p1 = CANONICAL_BASELINE.copy()
            p1["param_id"] = pid
            p1["tier"] = "TIER_4_ROLLING_CANONICAL"
            p1["window_length_years"] = y_len
            p1["start_date"] = start_dt
            p1["end_date"] = end_dt
            p1["start_date_idx"] = s_idx
            p1["end_date_idx"] = e_idx
            p1["filter_flags"] = CANONICAL_FILTER_FLAGS
            grid.append(p1)
            pid += 1

            # Next-Gen Upgraded variant
            p2 = CANONICAL_BASELINE.copy()
            p2["param_id"] = pid
            p2["tier"] = "TIER_4_ROLLING_NEXTGEN"
            p2["window_length_years"] = y_len
            p2["start_date"] = start_dt
            p2["end_date"] = end_dt
            p2["start_date_idx"] = s_idx
            p2["end_date_idx"] = e_idx
            p2["filter_flags"] = NEXTGEN_ALL_FLAGS
            grid.append(p2)
            pid += 1

    return grid


def generate_custom_parameter_grid(
    cube,
    lookbacks: Optional[List[int]] = None,
    ema_trends: Optional[List[int]] = None,
    top_ns: Optional[List[int]] = None,
    retrace_thresholds: Optional[List[float]] = None,
    schedules: Optional[List[str]] = None,
    max_per_sectors: Optional[List[int]] = None,
    sizing_modes: Optional[List[str]] = None,
    start_date: str = "2016-01-01",
    end_date: Optional[str] = None,
    filter_flags: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Generates a Cartesian product parameter grid from custom user specifications.
    Maps values to closest indices in cube.lookback_values and cube.ema_span_values.
    """
    if lookbacks is None:
        lookbacks = [252]
    if ema_trends is None:
        ema_trends = [200]
    if top_ns is None:
        top_ns = [20]
    if retrace_thresholds is None:
        retrace_thresholds = [0.80]
    if schedules is None:
        schedules = ["monthly"]
    if max_per_sectors is None:
        max_per_sectors = [2]
    if sizing_modes is None:
        sizing_modes = ["atr_risk_parity"]

    actual_end_date = end_date or cube.dates[-1]

    s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_date], default=0)
    e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= actual_end_date], default=cube.num_dates - 1)

    combos = list(itertools.product(
        schedules, top_ns, lookbacks, ema_trends, retrace_thresholds, max_per_sectors, sizing_modes
    ))

    grid = []
    pid = 0
    for sched, tn, lb, ema, ret, sec, sz in combos:
        l_idx = int(np.argmin([abs(v - lb) for v in cube.lookback_values]))
        e_span_idx = int(np.argmin([abs(v - ema) for v in cube.ema_span_values]))

        p = CANONICAL_BASELINE.copy()
        p["param_id"] = pid
        p["tier"] = "CUSTOM_SWEEP"
        p["schedule"] = sched
        p["schedule_idx"] = SCHEDULE_MAP.get(sched.lower(), 1)
        p["start_date"] = start_date
        p["end_date"] = actual_end_date
        p["start_date_idx"] = s_idx
        p["end_date_idx"] = e_idx
        p["top_n"] = int(tn)
        p["exit_buffer_rank"] = int(tn * 2.0)
        p["lookback"] = int(cube.lookback_values[l_idx])
        p["lookback_idx"] = l_idx
        p["ema_trend"] = int(cube.ema_span_values[e_span_idx])
        p["ema_idx"] = e_span_idx
        p["retrace_threshold"] = float(ret)
        p["max_per_sector"] = int(sec)
        p["sizing_mode"] = sz
        if filter_flags is not None:
            p["filter_flags"] = int(filter_flags)
        grid.append(p)
        pid += 1

    return grid

