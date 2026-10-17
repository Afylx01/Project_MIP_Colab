"""
grid.py - Parameter Space & Multi-Tier Matrix Generators for Project MIP
Supports Snapdragon 8 Gen 2 C99 NEON Brute Force Optimization.
"""

from typing import List, Dict, Any, Tuple, Optional
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


def generate_tier1_baseline_matrix(
    cube,
    use_residual_mom: bool = False,
    use_vol_targeting: bool = False,
    use_delivery_veto: bool = False,
) -> List[Dict[str, Any]]:
    """
    Tier 1: Canonical Baseline across 7 Macro Eras x 5 Rebalance Schedules = 35 runs.
    Supports optional residual momentum, volatility targeting, and delivery flow overlays.
    """
    flags = CANONICAL_FILTER_FLAGS
    if use_residual_mom:
        flags |= FILTER_RESIDUAL_MOM
    if use_vol_targeting:
        flags |= FILTER_VOL_TARGETING
    if use_delivery_veto:
        flags |= FILTER_DELIVERY_VETO

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
            p["filter_flags"] = flags
            p["use_residual_mom"] = use_residual_mom
            p["use_vol_targeting"] = use_vol_targeting
            p["use_delivery_veto"] = use_delivery_veto
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


def generate_random_time_duration_windows(
    cube,
    num_durations: int = 6,
    duration_lengths_years: Optional[List[float]] = None,
    seed: int = 42,
    include_full_era: bool = True,
) -> List[Dict[str, Any]]:
    """
    Generates random time duration windows across the historical date range.
    Each window represents a randomized market slice (e.g., 1y, 2y, 3y, 5y, 7y, 10y)
    with exact start/end date indices, dates, and descriptive labels.
    """
    if duration_lengths_years is None:
        duration_lengths_years = [1.0, 2.0, 3.0, 5.0, 7.0, 10.0]

    random.seed(seed)
    T = cube.num_dates
    min_start_idx = 350  # Warmup buffer to allow 252-day lookback + indicators

    windows = []
    if include_full_era:
        windows.append({
            "start_date_idx": 0,
            "end_date_idx": T - 1,
            "start_date": cube.dates[0],
            "end_date": cube.dates[-1],
            "duration_years": round(T / 252.0, 2),
            "duration_name": f"Full_Era ({cube.dates[0]} to {cube.dates[-1]})",
            "era": "FULL_ERA",
        })

    for y_len in duration_lengths_years:
        bars_len = int(y_len * 252)
        max_start = T - bars_len - 10
        if max_start <= min_start_idx:
            continue
        s_idx = random.randint(min_start_idx, max_start)
        e_idx = s_idx + bars_len
        windows.append({
            "start_date_idx": s_idx,
            "end_date_idx": e_idx,
            "start_date": cube.dates[s_idx],
            "end_date": cube.dates[e_idx],
            "duration_years": round((e_idx - s_idx) / 252.0, 2),
            "duration_name": f"Random_{y_len:.1f}Y ({cube.dates[s_idx]} to {cube.dates[e_idx]})",
            "era": f"RANDOM_{y_len:.1f}Y",
        })
        if len(windows) >= num_durations:
            break

    while len(windows) < num_durations:
        y_len = random.choice(duration_lengths_years)
        bars_len = int(y_len * 252)
        max_start = T - bars_len - 10
        if max_start <= min_start_idx:
            break
        s_idx = random.randint(min_start_idx, max_start)
        e_idx = s_idx + bars_len
        windows.append({
            "start_date_idx": s_idx,
            "end_date_idx": e_idx,
            "start_date": cube.dates[s_idx],
            "end_date": cube.dates[e_idx],
            "duration_years": round((e_idx - s_idx) / 252.0, 2),
            "duration_name": f"Random_{y_len:.1f}Y ({cube.dates[s_idx]} to {cube.dates[e_idx]})",
            "era": f"RANDOM_{y_len:.1f}Y",
        })

    return windows


def generate_tier3_hyperparameter_grid(
    cube,
    era_key: str = "2008-2026",
    schedules: List[str] = None,
    sample_size: Optional[int] = 61440,
    filter_flags: Optional[int] = None,
    use_residual_mom: bool = False,
    use_vol_targeting: bool = False,
    use_delivery_veto: bool = False,
    expanded_grid: bool = False,
    include_alpha_permutations: bool = False,
    include_random_durations: bool = False,
    num_random_durations: int = 6,
    duration_lengths_years: Optional[List[float]] = None,
    duration_windows: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Tier 3: Factorial Hyperparameter Grid across Top N, Lookbacks, EMAs, Buffers, Retrace, Sector Caps, Alphas,
    and optional Random Time Duration Dimension.
    Supports standard 61,440 full factorial matrix or expanded 1.7M+ to 13.8M+ multi-dimensional spaces.
    Produces institutional parameter sensitivity maps with robust regime cross-validation.
    """
    start_dt, end_dt, era_name = MACRO_ERAS.get(era_key, (cube.dates[0], cube.dates[-1], era_key))
    s_idx = min([cube.date_to_idx[d] for d in cube.dates if d >= start_dt], default=0)
    e_idx = max([cube.date_to_idx[d] for d in cube.dates if d <= end_dt], default=cube.num_dates - 1)

    if duration_windows is not None:
        duration_opts = duration_windows
    elif include_random_durations:
        duration_opts = generate_random_time_duration_windows(
            cube,
            num_durations=num_random_durations,
            duration_lengths_years=duration_lengths_years,
        )
    else:
        duration_opts = [{
            "start_date_idx": s_idx,
            "end_date_idx": e_idx,
            "start_date": start_dt,
            "end_date": end_dt,
            "duration_years": round((e_idx - s_idx) / 252.0, 2),
            "duration_name": era_name,
            "era": era_key,
        }]

    is_expanded = expanded_grid or (sample_size is not None and sample_size > 61440) or include_alpha_permutations or include_random_durations

    if is_expanded:
        if schedules is None:
            schedules = ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]
        top_n_opts = [5, 10, 15, 20, 25, 30]
        lookback_opts = list(range(len(LOOKBACK_VALUES)))  # 0, 1, 2, 3
        ema_opts = list(range(len(EMA_SPAN_VALUES)))       # 0, 1, 2, 3, 4
        buffer_opts = [10, 15, 20, 25, 30, 40]
        retrace_opts = [0.65, 0.70, 0.75, 0.80, 0.85, 0.90]
        sector_opts = [1, 2, 3, 4, 99]
        sizing_opts = ["atr_risk_parity", "equal_weight"]
        if include_alpha_permutations:
            alpha_opts = [
                (False, False, False),
                (True, False, False),
                (False, True, False),
                (False, False, True),
                (True, True, False),
                (True, False, True),
                (False, True, True),
                (True, True, True),
            ]
        else:
            alpha_opts = [(use_residual_mom, use_vol_targeting, use_delivery_veto)]
    else:
        if schedules is None:
            schedules = ["monthly", "quarterly", "weekly"]
        top_n_opts = [5, 10, 15, 20]
        lookback_opts = list(range(len(LOOKBACK_VALUES)))  # 0, 1, 2, 3
        ema_opts = list(range(len(EMA_SPAN_VALUES)))       # 0, 1, 2, 3, 4
        buffer_opts = [10, 20, 30, 40]
        retrace_opts = [0.70, 0.75, 0.80, 0.85]
        sector_opts = [1, 2, 3, 99]
        sizing_opts = ["atr_risk_parity", "equal_weight"]
        alpha_opts = [(use_residual_mom, use_vol_targeting, use_delivery_veto)]

    lens = [
        len(schedules),
        len(top_n_opts),
        len(lookback_opts),
        len(ema_opts),
        len(buffer_opts),
        len(retrace_opts),
        len(sector_opts),
        len(sizing_opts),
        len(alpha_opts),
        len(duration_opts),
    ]
    total_combinations = 1
    for l in lens:
        total_combinations *= l

    # If sampling requested and less than total space, perform fast indexed random sampling
    if sample_size is not None and 0 < sample_size < total_combinations:
        random.seed(42)
        selected_indices = random.sample(range(total_combinations), sample_size)
    else:
        selected_indices = range(total_combinations)

    grid = []
    base_flags = CANONICAL_FILTER_FLAGS if filter_flags is None else filter_flags

    for pid, idx in enumerate(selected_indices):
        rem = idx
        dur_info = duration_opts[rem % lens[9]]; rem //= lens[9]
        a_res, a_vol, a_veto = alpha_opts[rem % lens[8]]; rem //= lens[8]
        sz = sizing_opts[rem % lens[7]]; rem //= lens[7]
        sec = sector_opts[rem % lens[6]]; rem //= lens[6]
        ret = retrace_opts[rem % lens[5]]; rem //= lens[5]
        buf = buffer_opts[rem % lens[4]]; rem //= lens[4]
        ema_idx = ema_opts[rem % lens[3]]; rem //= lens[3]
        lb_idx = lookback_opts[rem % lens[2]]; rem //= lens[2]
        tn = top_n_opts[rem % lens[1]]; rem //= lens[1]
        sched = schedules[rem % lens[0]]

        p = CANONICAL_BASELINE.copy()
        p["param_id"] = pid
        p["tier"] = "TIER_3_GRID"
        p["era"] = dur_info["era"]
        p["duration_name"] = dur_info["duration_name"]
        p["duration_years"] = dur_info["duration_years"]
        p["schedule"] = sched
        p["schedule_idx"] = SCHEDULE_MAP[sched]
        p["start_date"] = dur_info["start_date"]
        p["end_date"] = dur_info["end_date"]
        p["start_date_idx"] = dur_info["start_date_idx"]
        p["end_date_idx"] = dur_info["end_date_idx"]
        p["top_n"] = tn
        p["lookback_idx"] = lb_idx
        p["lookback"] = LOOKBACK_VALUES[lb_idx]
        p["ema_idx"] = ema_idx
        p["ema_trend"] = EMA_SPAN_VALUES[ema_idx]
        p["exit_buffer_rank"] = buf
        p["retrace_threshold"] = ret
        p["max_per_sector"] = sec
        p["sizing_mode"] = sz

        f = base_flags
        if a_res:
            f |= FILTER_RESIDUAL_MOM
        if a_vol:
            f |= FILTER_VOL_TARGETING
        if a_veto:
            f |= FILTER_DELIVERY_VETO

        p["filter_flags"] = f
        p["use_residual_mom"] = a_res
        p["use_vol_targeting"] = a_vol
        p["use_delivery_veto"] = a_veto
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
    use_residual_mom: bool = False,
    use_vol_targeting: bool = False,
    use_delivery_veto: bool = False,
    include_random_durations: bool = False,
    num_random_durations: int = 4,
    duration_lengths_years: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """
    Generates a Cartesian product parameter grid from custom user specifications.
    Maps values to closest indices in cube.lookback_values and cube.ema_span_values.
    Supports optional residual momentum, volatility targeting, delivery flow overlays,
    and random time duration windows.
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

    if include_random_durations:
        dur_opts = generate_random_time_duration_windows(
            cube,
            num_durations=num_random_durations,
            duration_lengths_years=duration_lengths_years,
            include_full_era=False,
        )
    else:
        dur_opts = [{
            "start_date_idx": s_idx,
            "end_date_idx": e_idx,
            "start_date": start_date,
            "end_date": actual_end_date,
            "duration_years": round((e_idx - s_idx) / 252.0, 2),
            "duration_name": "Custom",
            "era": "CUSTOM",
        }]

    combos = list(itertools.product(
        schedules, top_ns, lookbacks, ema_trends, retrace_thresholds, max_per_sectors, sizing_modes, dur_opts
    ))

    flags = CANONICAL_FILTER_FLAGS if filter_flags is None else filter_flags
    if use_residual_mom:
        flags |= FILTER_RESIDUAL_MOM
    if use_vol_targeting:
        flags |= FILTER_VOL_TARGETING
    if use_delivery_veto:
        flags |= FILTER_DELIVERY_VETO

    grid = []
    pid = 0
    for sched, tn, lb, ema, ret, sec, sz, dur_info in combos:
        l_idx = int(np.argmin([abs(v - lb) for v in cube.lookback_values]))
        e_span_idx = int(np.argmin([abs(v - ema) for v in cube.ema_span_values]))

        p = CANONICAL_BASELINE.copy()
        p["param_id"] = pid
        p["tier"] = "CUSTOM_SWEEP"
        p["schedule"] = sched
        p["schedule_idx"] = SCHEDULE_MAP.get(sched.lower(), 1)
        p["start_date"] = dur_info["start_date"]
        p["end_date"] = dur_info["end_date"]
        p["start_date_idx"] = dur_info["start_date_idx"]
        p["end_date_idx"] = dur_info["end_date_idx"]
        p["duration_name"] = dur_info["duration_name"]
        p["duration_years"] = dur_info["duration_years"]
        p["era"] = dur_info["era"]
        p["top_n"] = int(tn)
        p["exit_buffer_rank"] = int(tn * 2.0)
        p["lookback"] = int(cube.lookback_values[l_idx])
        p["lookback_idx"] = l_idx
        p["ema_trend"] = int(cube.ema_span_values[e_span_idx])
        p["ema_idx"] = e_span_idx
        p["retrace_threshold"] = float(ret)
        p["max_per_sector"] = int(sec)
        p["sizing_mode"] = sz
        p["filter_flags"] = int(flags)
        p["use_residual_mom"] = bool(use_residual_mom)
        p["use_vol_targeting"] = bool(use_vol_targeting)
        p["use_delivery_veto"] = bool(use_delivery_veto)
        grid.append(p)
        pid += 1

    return grid

