"""
cube_builder.py - High-Performance In-Memory Tensor Cube Generator for Project MIP
Builds C-contiguous float32 indicator arrays for ultra-fast multi-schedule, multi-era simulation.
"""

import sys
import math
import datetime
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_base_dir, get_db_path, load_universe_constituents, load_symbol_sector_map
from core.portfolio import normalize_sector
from core.benchmark_validator import validate_benchmark_dataframe, compute_benchmark_indicators
from nextgen.volatility_targeting import compute_ewma_realized_volatility

# Canonical Lookbacks & EMA Spans
DEFAULT_LOOKBACKS = [126, 189, 252, 315]
DEFAULT_EMA_SPANS = [50, 100, 150, 200, 250]


class TensorCubeContainer:
    """Holds contiguous C-order NumPy arrays for the brute force simulation engine."""

    def __init__(
        self,
        dates: List[str],
        symbols: List[str],
        schedule_indices_map: Dict[str, np.ndarray],
        benchmark_regime: np.ndarray,
        sector_ids: np.ndarray,
        open_px: np.ndarray,
        close_px: np.ndarray,
        atr_14: np.ndarray,
        volar_cubes: np.ndarray,
        high_cubes: np.ndarray,
        res_mom_cubes: np.ndarray,
        ema_cubes: np.ndarray,
        rs_pass_cubes: np.ndarray,
        vol_target_scalar: np.ndarray,
        delivery_veto_plane: np.ndarray,
        lookback_values: List[int],
        ema_span_values: List[int],
        sector_names: List[str],
        bench_closes: Optional[np.ndarray] = None,
        benchmark_name: str = "NIFTY500",
    ):
        self.dates = dates
        self.symbols = symbols
        self.num_dates = len(dates)
        self.num_symbols = len(symbols)
        self.benchmark_name = benchmark_name

        self.schedule_names = ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]
        self.num_schedules = len(self.schedule_names)

        # Concatenate rebalance indices for all schedules into a single 1D int32 array
        self.schedule_offsets = np.zeros(8, dtype=np.uint32)
        self.schedule_lengths = np.zeros(8, dtype=np.uint32)
        rebal_list = []
        cur_offset = 0

        for s_idx, s_name in enumerate(self.schedule_names):
            arr = schedule_indices_map.get(s_name, np.empty(0, dtype=np.int32))
            arr_len = len(arr)
            self.schedule_offsets[s_idx] = cur_offset
            self.schedule_lengths[s_idx] = arr_len
            rebal_list.append(arr)
            cur_offset += arr_len

        self.rebalance_indices = np.ascontiguousarray(np.concatenate(rebal_list), dtype=np.int32)
        self.num_rebalances = self.schedule_lengths[1] # monthly length for backward compatibility

        self.benchmark_regime = np.ascontiguousarray(benchmark_regime, dtype=np.uint8)
        self.sector_ids = np.ascontiguousarray(sector_ids, dtype=np.uint8)

        self.open_px = np.ascontiguousarray(open_px, dtype=np.float32)
        self.close_px = np.ascontiguousarray(close_px, dtype=np.float32)
        self.atr_14 = np.ascontiguousarray(atr_14, dtype=np.float32)

        self.volar_cubes = np.ascontiguousarray(volar_cubes, dtype=np.float32)
        self.high_cubes = np.ascontiguousarray(high_cubes, dtype=np.float32)
        self.res_mom_cubes = np.ascontiguousarray(res_mom_cubes, dtype=np.float32)
        self.ema_cubes = np.ascontiguousarray(ema_cubes, dtype=np.float32)
        self.rs_pass_cubes = np.ascontiguousarray(rs_pass_cubes, dtype=np.uint8)

        self.vol_target_scalar = np.ascontiguousarray(vol_target_scalar, dtype=np.float32)
        self.delivery_veto_plane = np.ascontiguousarray(delivery_veto_plane, dtype=np.uint8)

        if bench_closes is not None:
            self.bench_closes = np.ascontiguousarray(bench_closes, dtype=np.float32)
        else:
            self.bench_closes = np.ones(self.num_dates, dtype=np.float32)

        self.lookback_values = lookback_values
        self.ema_span_values = ema_span_values
        self.sector_names = sector_names

        self.date_to_idx = {d: i for i, d in enumerate(dates)}
        self.symbol_to_idx = {s: i for i, s in enumerate(symbols)}

    @property
    def memory_footprint_mb(self) -> float:
        total_bytes = (
            self.rebalance_indices.nbytes
            + self.benchmark_regime.nbytes
            + self.sector_ids.nbytes
            + (self.bench_closes.nbytes if hasattr(self, "bench_closes") else 0)
            + self.open_px.nbytes
            + self.close_px.nbytes
            + self.atr_14.nbytes
            + self.volar_cubes.nbytes
            + self.high_cubes.nbytes
            + self.res_mom_cubes.nbytes
            + self.ema_cubes.nbytes
            + self.rs_pass_cubes.nbytes
            + self.vol_target_scalar.nbytes
            + self.delivery_veto_plane.nbytes
        )
        return total_bytes / (1024 * 1024)


def build_tensor_cube(
    start_date: str = "2007-01-02",
    end_date: Optional[str] = None,
    universe_name: str = "NIFTY750",
    benchmark_name: str = "NIFTY500",
    lookback_values: Optional[List[int]] = None,
    ema_span_values: Optional[List[int]] = None,
    base_dir: Optional[Path] = None,
) -> TensorCubeContainer:
    """
    Constructs the precomputed multi-schedule, multi-lookback tensor cube for NIFTY 750 / 500 / ALL.
    Precomputes Volar, 52w Highs, Residual Momentum, EMAs, RS, and Volatility Targeting.
    """
    if lookback_values is None:
        lookback_values = DEFAULT_LOOKBACKS
    if ema_span_values is None:
        ema_span_values = DEFAULT_EMA_SPANS

    base_path = Path(base_dir) if base_dir else get_base_dir()
    db_path = get_db_path()
    if end_date is None:
        from core.data_engine import get_latest_date
        end_date = get_latest_date()

    print(f"\n[CubeBuilder] Loading constituents for universe '{universe_name}'...")
    sym_set = load_universe_constituents(universe_name)
    all_symbols = sorted(list(sym_set))
    N = len(all_symbols)
    print(f"[CubeBuilder] Loaded {N} constituents from {universe_name}.")

    # Sector mapping
    raw_sector_map = load_symbol_sector_map()
    unique_sectors = sorted(list(set(normalize_sector(raw_sector_map.get(s, "OTHER")) for s in all_symbols)))
    sector_to_id = {sec: i for i, sec in enumerate(unique_sectors)}
    sector_ids = np.array([sector_to_id[normalize_sector(raw_sector_map.get(s, "OTHER"))] for s in all_symbols], dtype=np.uint8)

    # Load raw price bars from SQLite
    print(f"[CubeBuilder] Querying raw price bars from SQLite ({start_date} to {end_date})...")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    placeholders = ",".join(["?"] * N)
    query = (
        f"SELECT date, symbol, open, high, low, close, volume FROM prices "
        f"WHERE symbol IN ({placeholders}) AND date >= ? AND date <= ? "
        f"ORDER BY symbol, date"
    )
    raw_bars = pd.read_sql_query(query, conn, params=all_symbols + [start_date, end_date])
    conn.close()

    raw_bars["date"] = raw_bars["date"].astype(str)
    all_dates = sorted(raw_bars["date"].unique().tolist())
    T = len(all_dates)
    print(f"[CubeBuilder] Loaded {len(raw_bars):,} price bars across {T} trading dates.")

    # Load and validate benchmark (user-selected)
    print(f"[CubeBuilder] Resolving benchmark series for '{benchmark_name}'...")
    from core.benchmark_validator import resolve_benchmark_dataframe
    b_df = resolve_benchmark_dataframe(
        benchmark_name=benchmark_name,
        base_dir=base_path,
        required_dates=all_dates,
        universe_name=universe_name,
    )
    b_df["date"] = b_df["date"].astype(str)
    b_df = b_df.sort_values("date").reset_index(drop=True)
    bench_close_map = dict(zip(b_df["date"], b_df["close"]))
    bench_bull_map = dict(zip(b_df["date"], b_df["close"] >= b_df["ema_20"]))

    benchmark_regime = np.array([1 if bench_bull_map.get(d, True) else 0 for d in all_dates], dtype=np.uint8)
    bench_closes = np.array([bench_close_map.get(d, np.nan) for d in all_dates], dtype=np.float32)

    sym_to_idx = {s: i for i, s in enumerate(all_symbols)}
    date_to_idx = {d: i for i, d in enumerate(all_dates)}

    print(f"[CubeBuilder] Allocating price matrix for {T} dates x {N} symbols...")
    open_px = np.zeros((T, N), dtype=np.float32)
    close_px = np.zeros((T, N), dtype=np.float32)
    high_px = np.zeros((T, N), dtype=np.float32)
    low_px = np.zeros((T, N), dtype=np.float32)
    vol_mat = np.zeros((T, N), dtype=np.float32)

    d_indices = raw_bars["date"].map(date_to_idx).to_numpy(dtype=np.int32)
    s_indices = raw_bars["symbol"].map(sym_to_idx).to_numpy(dtype=np.int32)

    open_px[d_indices, s_indices] = raw_bars["open"].to_numpy(dtype=np.float32)
    close_px[d_indices, s_indices] = raw_bars["close"].to_numpy(dtype=np.float32)
    high_px[d_indices, s_indices] = raw_bars["high"].to_numpy(dtype=np.float32)
    low_px[d_indices, s_indices] = raw_bars["low"].to_numpy(dtype=np.float32)
    vol_mat[d_indices, s_indices] = raw_bars["volume"].to_numpy(dtype=np.float32)

    # True Range & ATR-14
    print("[CubeBuilder] Computing vectorized ATR-14...")
    prev_close = np.vstack([close_px[:1], close_px[:-1]])
    tr1 = high_px - low_px
    tr2 = np.abs(high_px - prev_close)
    tr3 = np.abs(low_px - prev_close)
    tr = np.maximum(tr1, np.maximum(tr2, tr3))

    atr_14 = np.zeros((T, N), dtype=np.float32)
    cumsum_tr = np.cumsum(tr, axis=0)
    atr_14[14:] = (cumsum_tr[14:] - cumsum_tr[:-14]) / 14.0
    atr_14[:14] = cumsum_tr[:14] / np.arange(1, 15)[:, None]
    atr_14 = np.where(atr_14 > 0, atr_14, close_px * 0.03)

    # Precompute daily returns for Volar & Residual Momentum
    daily_ret = np.zeros((T, N), dtype=np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        daily_ret[1:] = np.where(close_px[:-1] > 0, (close_px[1:] / close_px[:-1]) - 1.0, 0.0)

    # Approximate benchmark return as universe median return where benchmark is nan
    bench_series = pd.Series(bench_closes).bfill().ffill().fillna(1000.0)
    bench_closes = bench_series.to_numpy(dtype=np.float32)
    b_ret = bench_series.pct_change(fill_method=None).fillna(0.0).to_numpy(dtype=np.float32)
    if np.isnan(b_ret).any() or (b_ret == 0.0).mean() > 0.5:
        b_ret = np.nanmedian(daily_ret, axis=1)

    daily_rf = 0.065 / 252.0
    bench_excess = b_ret - daily_rf
    s_bench_excess = pd.Series(bench_excess)

    num_lb = len(lookback_values)
    volar_cubes = np.zeros((num_lb, T, N), dtype=np.float32)
    high_cubes = np.zeros((num_lb, T, N), dtype=np.float32)
    res_mom_cubes = np.zeros((num_lb, T, N), dtype=np.float32)

    df_ret = pd.DataFrame(daily_ret)
    df_high = pd.DataFrame(high_px)
    stock_mat = daily_ret - daily_rf
    df_stock_mat = pd.DataFrame(stock_mat)

    print(f"[CubeBuilder] Precomputing {num_lb} lookback cubes for Volar, Highs & Residual Momentum...")
    for l_idx, lb in enumerate(lookback_values):
        # 1. Volar (1-year return / rolling annualized std)
        ret_lb = np.zeros((T, N), dtype=np.float32)
        with np.errstate(divide="ignore", invalid="ignore"):
            ret_lb[lb:] = np.where(close_px[:-lb] > 0, (close_px[lb:] / close_px[:-lb]) - 1.0, 0.0)

        rolling_std = df_ret.rolling(lb, min_periods=min(50, lb)).std().to_numpy(dtype=np.float32) * np.sqrt(252.0)
        rolling_std = np.clip(rolling_std, 0.05, 10.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            volar_cubes[l_idx] = np.nan_to_num(ret_lb / rolling_std, nan=0.0, posinf=0.0, neginf=0.0)

        # 2. Rolling High
        high_cubes[l_idx] = df_high.rolling(lb, min_periods=min(50, lb)).max().to_numpy(dtype=np.float32)

        # 3. Residual Momentum (Vectorized 2D Blitz et al. with 21-day reversal guard)
        skip_recent = 21
        effective_lb = max(lb - skip_recent, 30)

        mean_x = df_stock_mat.rolling(lb, min_periods=min(50, lb)).mean().to_numpy()
        mean_y = s_bench_excess.rolling(lb, min_periods=min(50, lb)).mean().to_numpy()[:, None]
        var_y = np.clip(s_bench_excess.rolling(lb, min_periods=min(50, lb)).var().to_numpy()[:, None], 1e-8, None)

        mat_xy = stock_mat * bench_excess[:, None]
        mean_xy = pd.DataFrame(mat_xy).rolling(lb, min_periods=min(50, lb)).mean().to_numpy()
        w_factor = float(lb) / float(lb - 1)
        cov_xy = w_factor * (mean_xy - (mean_x * mean_y))

        beta = np.where(var_y > 1e-8, cov_xy / var_y, 1.0)
        alpha = mean_x - (beta * mean_y)

        eps = stock_mat - (alpha + beta * bench_excess[:, None])
        df_eps = pd.DataFrame(eps)
        eps_std = np.clip(df_eps.rolling(lb, min_periods=min(50, lb)).std().to_numpy(), 1e-4, None)

        shifted_eps = df_eps.shift(skip_recent)
        eps_sum = shifted_eps.rolling(effective_lb, min_periods=min(30, effective_lb)).sum().to_numpy()
        res_mom_cubes[l_idx] = np.nan_to_num(eps_sum / (eps_std * np.sqrt(effective_lb)), nan=0.0).astype(np.float32)

    # Precompute EMAs across spans
    num_ema = len(ema_span_values)
    ema_cubes = np.zeros((num_ema, T, N), dtype=np.float32)
    rs_pass_cubes = np.zeros((num_ema, T, N), dtype=np.uint8)

    print(f"[CubeBuilder] Precomputing {num_ema} EMA cubes and Relative Strength filters...")
    df_close = pd.DataFrame(close_px)
    for e_idx, span in enumerate(ema_span_values):
        ema_cubes[e_idx] = df_close.ewm(span=span, adjust=True, min_periods=min(50, span)).mean().to_numpy(dtype=np.float32)

        # Relative strength vs benchmark
        bench_col = bench_closes[:, None]
        rs_ratio = np.where(bench_col > 0, close_px / bench_col, np.nan)
        df_rs = pd.DataFrame(rs_ratio)
        rs_ema = df_rs.ewm(span=span, adjust=True, min_periods=min(50, span)).mean().to_numpy(dtype=np.float32)
        rs_pass = (rs_ratio > rs_ema) & np.isfinite(rs_ratio) & np.isfinite(rs_ema)
        rs_pass_cubes[e_idx] = np.where(rs_pass, 1, 0).astype(np.uint8)

    # Precompute Volatility Targeting Cash Shield scalar
    print("[CubeBuilder] Precomputing EWMA Volatility Targeting & Cash Shield...")
    s_b_ret = pd.Series(b_ret)
    ewma_vol = compute_ewma_realized_volatility(s_b_ret, lambda_decay=0.94)
    target_annual_vol = 0.12
    vol_target_scalar = np.clip(target_annual_vol / np.maximum(ewma_vol.to_numpy(dtype=np.float32), 0.05), 0.20, 1.0)

    # Precompute Delivery Microstructure Veto
    # Using Close Location Value (CLV < -0.80) as distribution veto
    print("[CubeBuilder] Precomputing Microstructure Delivery Flow Veto plane...")
    span_px = high_px - low_px
    with np.errstate(divide="ignore", invalid="ignore"):
        clv_mat = np.where(span_px > 0, (2.0 * close_px - high_px - low_px) / span_px, 0.0)
    delivery_veto_plane = np.where(clv_mat < -0.80, 1, 0).astype(np.uint8)

    # Precompute All 5 Rebalance Schedules
    print("[CubeBuilder] Building 5 Multi-Schedule Rebalance Index Tables...")
    df_d = pd.DataFrame({"date": all_dates})
    df_d["dt"] = pd.to_datetime(df_d["date"])
    df_d["year"] = df_d["dt"].dt.year
    df_d["month"] = df_d["dt"].dt.strftime("%Y-%m")
    df_d["week"] = df_d["dt"].dt.strftime("%Y-W%V")
    df_d["quarter"] = df_d["year"].astype(str) + "-Q" + (((df_d["dt"].dt.month - 1) // 3) + 1).astype(str)
    df_d["half_year"] = df_d["year"].astype(str) + "-H" + (((df_d["dt"].dt.month - 1) // 6) + 1).astype(str)

    schedule_indices_map = {
        "weekly": np.array([date_to_idx[d] for d in df_d.groupby("week")["date"].last() if d in date_to_idx], dtype=np.int32),
        "monthly": np.array([date_to_idx[d] for d in df_d.groupby("month")["date"].last() if d in date_to_idx], dtype=np.int32),
        "quarterly": np.array([date_to_idx[d] for d in df_d.groupby("quarter")["date"].last() if d in date_to_idx], dtype=np.int32),
        "half_yearly": np.array([date_to_idx[d] for d in df_d.groupby("half_year")["date"].last() if d in date_to_idx], dtype=np.int32),
        "yearly": np.array([date_to_idx[d] for d in df_d.groupby("year")["date"].last() if d in date_to_idx], dtype=np.int32),
    }

    print(f"  • Weekly:      {len(schedule_indices_map['weekly']):,} rebalances")
    print(f"  • Monthly:     {len(schedule_indices_map['monthly']):,} rebalances")
    print(f"  • Quarterly:   {len(schedule_indices_map['quarterly']):,} rebalances")
    print(f"  • Half-Yearly: {len(schedule_indices_map['half_yearly']):,} rebalances")
    print(f"  • Yearly:      {len(schedule_indices_map['yearly']):,} rebalances")

    container = TensorCubeContainer(
        dates=all_dates,
        symbols=all_symbols,
        schedule_indices_map=schedule_indices_map,
        benchmark_regime=benchmark_regime,
        sector_ids=sector_ids,
        open_px=open_px,
        close_px=close_px,
        atr_14=atr_14,
        volar_cubes=volar_cubes,
        high_cubes=high_cubes,
        res_mom_cubes=res_mom_cubes,
        ema_cubes=ema_cubes,
        rs_pass_cubes=rs_pass_cubes,
        vol_target_scalar=vol_target_scalar,
        delivery_veto_plane=delivery_veto_plane,
        lookback_values=lookback_values,
        ema_span_values=ema_span_values,
        sector_names=unique_sectors,
        bench_closes=bench_closes,
        benchmark_name=benchmark_name,
    )

    print(f"\n[CubeBuilder] Tensor Cube created: {container.memory_footprint_mb:.2f} MB RAM footprint.")
    print(f"[CubeBuilder] Dates: {T} ({all_dates[0]} to {all_dates[-1]}), Symbols: {N} ({universe_name}).")
    return container
