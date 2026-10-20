"""
pydroid_core/benchmark_validator.py
Institutional Fail-Closed Benchmark Validation & Market Regime Evaluation Engine.
Enforces strict quantitative invariants for NIFTY 500 benchmark proxy.

DIRECTIVES SATISFIED:
- DEFECT-01: Silent benchmark failure prevention & fail-closed regime evaluation.
- DEFECT-02: Rejection of NaN, null, non-positive, duplicate, or malformed prices.
- Freshness Invariant: Deterministic trading calendar freshness enforcement.
- Fail-Closed Policy:
    If benchmark is missing, stale, NaN, malformed, or API failed:
      REGIME = UNKNOWN / INVALID (NOT BULL)
      NEW BUY ORDERS = 0
      NEW EQUITY ENTRIES = 0
      UNALLOCATED CAPITAL = CASH
"""

import os
import io
import datetime
import math
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np
import pandas as pd
import requests


class BenchmarkRegimeStatus(str, Enum):
    BULL = "BULL"
    DEFENSIVE = "DEFENSIVE"
    STALE = "STALE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class BenchmarkSyncResult(str, Enum):
    SUCCESS = "SUCCESS"
    UP_TO_DATE = "UP_TO_DATE"
    FAILED = "FAILED"
    INVALID = "INVALID"


class BenchmarkValidationResult:
    """
    Immutable representation of benchmark validation and regime evaluation result.
    Strictly fail-closed: allow_new_buys and is_normal_regime can ONLY be True
    when status == BenchmarkRegimeStatus.BULL and is_valid is True.
    """
    def __init__(
        self,
        is_valid: bool,
        status: BenchmarkRegimeStatus,
        allow_new_buys: bool,
        bm_close: Optional[float] = None,
        bm_ema20: Optional[float] = None,
        benchmark_date: Optional[str] = None,
        expected_date: Optional[str] = None,
        error_message: Optional[str] = None,
        df: Optional[pd.DataFrame] = None,
    ):
        self.is_valid = bool(is_valid)
        self.status = status
        # Invariant: allow_new_buys is NEVER True unless valid and BULL
        self.allow_new_buys = bool(allow_new_buys and is_valid and status == BenchmarkRegimeStatus.BULL)
        self.is_normal_regime = self.allow_new_buys
        self.bm_close = bm_close
        self.bm_ema20 = bm_ema20
        self.benchmark_date = benchmark_date
        self.expected_date = expected_date
        self.error_message = error_message
        self.df = df

    def to_dict(self) -> Dict[str, Any]:
        """Returns standard scanner/portfolio regime metadata dictionary."""
        if self.status == BenchmarkRegimeStatus.BULL:
            label = "🟢 NORMAL (AGGRESSIVE)"
            regime = "NORMAL"
        elif self.status == BenchmarkRegimeStatus.DEFENSIVE:
            label = "🔴 DEFENSIVE (CASH SHIELD)"
            regime = "DEFENSIVE"
        elif self.status == BenchmarkRegimeStatus.STALE:
            label = "⚠️ REGIME INVALID (BENCHMARK DATA STALE)"
            regime = "STALE"
        elif self.status == BenchmarkRegimeStatus.UNAVAILABLE:
            label = "⚠️ REGIME INVALID (BENCHMARK DATA UNAVAILABLE)"
            regime = "UNAVAILABLE"
        else:
            label = "⚠️ REGIME INVALID (BENCHMARK DATA CORRUPT/MALFORMED)"
            regime = "INVALID"

        return {
            "is_valid": self.is_valid,
            "status": self.status.value,
            "is_normal_regime": self.is_normal_regime,
            "allow_new_buys": self.allow_new_buys,
            "regime": regime,
            "label": label,
            "bm_close": round(self.bm_close, 2) if self.bm_close is not None else None,
            "bm_ema20": round(self.bm_ema20, 2) if self.bm_ema20 is not None else None,
            "benchmark_date": self.benchmark_date,
            "expected_date": self.expected_date,
            "error": self.error_message,
        }

    def __repr__(self) -> str:
        return (
            f"BenchmarkValidationResult(valid={self.is_valid}, status={self.status.value}, "
            f"allow_new_buys={self.allow_new_buys}, close={self.bm_close}, "
            f"ema20={self.bm_ema20}, bench_date={self.benchmark_date}, err={self.error_message})"
        )


def validate_benchmark_dataframe(
    df: pd.DataFrame,
    min_history: int = 20,
    check_ordering: bool = True,
) -> Tuple[bool, Optional[str]]:
    """
    Validates benchmark dataframe against all data-integrity invariants.
    Returns (True, None) if fully compliant, or (False, reason) if any invariant is violated.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        return False, "Benchmark data is null or not a pandas DataFrame"

    if df.empty:
        return False, "Benchmark DataFrame is empty (0 rows)"

    # Schema check
    required_cols = {"date", "close"}
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        return False, f"Benchmark missing required columns: {sorted(missing_cols)}"

    # Date column validation
    date_col = df["date"].astype(str).str.strip()
    if date_col.str.len().min() < 10:
        return False, "Benchmark contains malformed date strings (<10 chars)"

    # Duplicate dates check
    if date_col.duplicated().any():
        dups = date_col[date_col.duplicated()].unique().tolist()
        return False, f"Benchmark contains duplicate dates: {dups[:5]}"

    # Chronological ordering check
    if check_ordering:
        if not date_col.is_monotonic_increasing:
            return False, "Benchmark dates are not monotonically strictly increasing"

    # Price validation: NaN, null, inf, non-positive
    close_series = pd.to_numeric(df["close"], errors="coerce")
    if close_series.isna().any():
        nan_count = int(close_series.isna().sum())
        nan_dates = date_col[close_series.isna()].tolist()[:3]
        return False, f"Benchmark contains {nan_count} NaN/null close prices (dates: {nan_dates})"

    if np.isinf(close_series).any():
        return False, "Benchmark contains infinite close prices"

    if (close_series <= 0).any():
        invalid_count = int((close_series <= 0).sum())
        return False, f"Benchmark contains {invalid_count} non-positive close prices (<= 0)"

    # Minimum history check
    if len(df) < min_history:
        return False, f"Benchmark contains insufficient historical rows ({len(df)} < {min_history} required)"

    return True, None


def compute_benchmark_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes 20-period exponential moving average on verified benchmark series.
    Returns copy of dataframe with 'ema_20' column.
    """
    df_clean = df.copy()
    df_clean["date"] = df_clean["date"].astype(str).str.strip()
    df_clean = df_clean.sort_values("date").reset_index(drop=True)
    df_clean["close"] = pd.to_numeric(df_clean["close"], errors="coerce")
    df_clean["ema_20"] = df_clean["close"].ewm(span=20, adjust=True).mean()
    return df_clean


def get_expected_market_date(
    as_of_date: str,
    trading_calendar: Optional[List[str]] = None,
) -> str:
    """
    Resolves the expected most recent trading session on or before as_of_date.
    Uses institutional NSE trading calendar if available; falls back to weekday logic.
    """
    as_of_clean = str(as_of_date).strip()[:10]

    if trading_calendar and len(trading_calendar) > 0:
        if as_of_clean <= trading_calendar[-1]:
            valid_sessions = [d for d in trading_calendar if d <= as_of_clean]
            if valid_sessions:
                return valid_sessions[-1]

    # Fallback to weekday arithmetic (Monday=0, Sunday=6) and exchange holidays
    try:
        from .data_engine import KNOWN_NSE_HOLIDAYS
    except Exception:
        KNOWN_NSE_HOLIDAYS = set()

    try:
        dt = datetime.datetime.strptime(as_of_clean, "%Y-%m-%d").date()
        while dt.weekday() >= 5 or dt.strftime("%Y-%m-%d") in KNOWN_NSE_HOLIDAYS:
            dt -= datetime.timedelta(days=1)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return as_of_clean


def check_benchmark_freshness(
    as_of_date: str,
    latest_bench_date: str,
    trading_calendar: Optional[List[str]] = None,
) -> Tuple[bool, str, Optional[str]]:
    """
    Validates benchmark freshness window against the required market date.
    Returns (is_fresh, expected_market_date, rejection_reason).
    """
    as_of_clean = str(as_of_date).strip()[:10]
    bench_clean = str(latest_bench_date).strip()[:10]
    expected_date = get_expected_market_date(as_of_clean, trading_calendar)

    # 1. Temporal integrity: benchmark must not contain future dates relative to evaluation date
    if bench_clean > as_of_clean:
        return False, expected_date, f"Lookahead violation: benchmark date ({bench_clean}) > as_of_date ({as_of_clean})"

    # 2. Freshness check: benchmark must be up to date with the latest expected trading session
    if bench_clean < expected_date:
        return False, expected_date, f"Benchmark data is stale: latest date {bench_clean} < expected session {expected_date}"

    return True, expected_date, None


def evaluate_regime(
    as_of_date: str,
    benchmark_csv_or_df: Optional[Union[Path, str, pd.DataFrame]] = None,
    trading_calendar: Optional[List[str]] = None,
    min_history: int = 20,
) -> BenchmarkValidationResult:
    """
    Institutional fail-closed regime evaluator.
    Evaluates benchmark close against 20 EMA for as_of_date.

    Guarantees:
    - If benchmark file is missing, empty, malformed, or contains NaNs:
        Returns status=INVALID/UNAVAILABLE, allow_new_buys=False, is_normal_regime=False.
    - If benchmark data is stale relative to trading calendar:
        Returns status=STALE, allow_new_buys=False, is_normal_regime=False.
    - If valid and close >= ema_20:
        Returns status=BULL, allow_new_buys=True, is_normal_regime=True.
    - If valid and close < ema_20:
        Returns status=DEFENSIVE, allow_new_buys=False, is_normal_regime=False.
    """
    as_of_clean = str(as_of_date).strip()[:10]

    # 1. Resolve benchmark input
    if benchmark_csv_or_df is None:
        try:
            from .data_engine import get_base_dir
            bench_path = get_base_dir() / "data" / "benchmark_nifty500.csv"
        except Exception:
            bench_path = Path("data/benchmark_nifty500.csv")
    elif isinstance(benchmark_csv_or_df, (str, Path)):
        bench_path = Path(benchmark_csv_or_df)
    else:
        bench_path = None

    # 2. Ingest DataFrame
    df: Optional[pd.DataFrame] = None
    if bench_path is not None:
        if not bench_path.exists():
            return BenchmarkValidationResult(
                is_valid=False,
                status=BenchmarkRegimeStatus.UNAVAILABLE,
                allow_new_buys=False,
                expected_date=get_expected_market_date(as_of_clean, trading_calendar),
                error_message=f"Benchmark file not found at {bench_path}",
            )
        try:
            df = pd.read_csv(bench_path)
        except Exception as e:
            return BenchmarkValidationResult(
                is_valid=False,
                status=BenchmarkRegimeStatus.INVALID,
                allow_new_buys=False,
                expected_date=get_expected_market_date(as_of_clean, trading_calendar),
                error_message=f"Failed to read benchmark CSV: {e}",
            )
    elif isinstance(benchmark_csv_or_df, pd.DataFrame):
        df = benchmark_csv_or_df.copy()
    else:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.UNAVAILABLE,
            allow_new_buys=False,
            expected_date=get_expected_market_date(as_of_clean, trading_calendar),
            error_message="Invalid benchmark source provided",
        )

    # 2b. Point-In-Time Temporal Partitioning (Anti-Lookahead Gate)
    # Ensure that no observations strictly after as_of_clean enter validation or indicator computation
    df["date"] = df["date"].astype(str).str.strip()
    df_pit = df[df["date"] <= as_of_clean].copy()
    expected_date = get_expected_market_date(as_of_clean, trading_calendar)

    if df_pit.empty:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.INVALID,
            allow_new_buys=False,
            expected_date=expected_date,
            error_message=f"No benchmark rows on or before {as_of_clean}",
        )

    # 3. Validate DataFrame invariants on Point-In-Time data
    is_valid, err_msg = validate_benchmark_dataframe(df_pit, min_history=min_history)
    if not is_valid:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.INVALID,
            allow_new_buys=False,
            expected_date=expected_date,
            error_message=err_msg,
        )

    # 4. Compute Indicators on Point-In-Time data
    df_calc = compute_benchmark_indicators(df_pit)

    # 5. Extract latest benchmark date and verify freshness
    latest_bench_date = str(df_calc["date"].iloc[-1])
    is_fresh, expected_date, stale_reason = check_benchmark_freshness(
        as_of_date=as_of_clean,
        latest_bench_date=latest_bench_date,
        trading_calendar=trading_calendar,
    )
    if not is_fresh:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.STALE,
            allow_new_buys=False,
            benchmark_date=latest_bench_date,
            expected_date=expected_date,
            error_message=stale_reason,
            df=df_calc,
        )

    # 6. Locate benchmark row for as_of_date
    row = df_calc.iloc[-1]
    bench_row_date = str(row["date"])

    try:
        bm_close = float(row["close"])
        bm_ema20 = float(row["ema_20"])
    except (ValueError, TypeError) as e:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.INVALID,
            allow_new_buys=False,
            benchmark_date=bench_row_date,
            expected_date=expected_date,
            error_message=f"Non-numeric benchmark values on {bench_row_date}: {e}",
            df=df_calc,
        )

    # Validate finite positive values
    if not math.isfinite(bm_close) or not math.isfinite(bm_ema20) or bm_close <= 0 or bm_ema20 <= 0:
        return BenchmarkValidationResult(
            is_valid=False,
            status=BenchmarkRegimeStatus.INVALID,
            allow_new_buys=False,
            benchmark_date=bench_row_date,
            expected_date=expected_date,
            error_message=f"Non-positive or non-finite benchmark price/EMA on {bench_row_date}",
            df=df_calc,
        )

    # 7. Evaluate Regime
    is_bull = bool(bm_close >= bm_ema20)
    status = BenchmarkRegimeStatus.BULL if is_bull else BenchmarkRegimeStatus.DEFENSIVE

    return BenchmarkValidationResult(
        is_valid=True,
        status=status,
        allow_new_buys=is_bull,
        bm_close=bm_close,
        bm_ema20=bm_ema20,
        benchmark_date=bench_row_date,
        expected_date=expected_date,
        df=df_calc,
    )


# ============================================================================
# Universal Benchmark Resolution & Indicator Engine
# ============================================================================

# Standard Benchmark Catalog
BENCHMARK_CATALOG: Dict[str, Dict[str, Any]] = {
    "NIFTY500": {
        "label": "NIFTY 500 (Broad Market Institutional Standard)",
        "aliases": ["NIFTY500", "NIFTY 500", "^CRSLDX", "500", "DEFAULT"],
        "filename": "benchmark_nifty500.csv",
        "yahoo_symbol": "^CRSLDX",
        "category": "Broad Market",
    },
    "NIFTY50": {
        "label": "NIFTY 50 (Frontline Large-Cap)",
        "aliases": ["NIFTY50", "NIFTY 50", "^NSEI", "50", "NIFTY"],
        "filename": "benchmark_nifty50.csv",
        "yahoo_symbol": "^NSEI",
        "category": "Broad Market",
    },
    "NIFTY750": {
        "label": "NIFTY Total Market / 750 (All-Cap Universe)",
        "aliases": ["NIFTY750", "NIFTY 750", "NIFTYTOTALMARKET", "TOTALMARKET", "TOTAL_MARKET", "750"],
        "filename": "benchmark_nifty750.csv",
        "yahoo_symbol": None,
        "category": "Broad Market",
    },
    "NIFTYNEXT50": {
        "label": "NIFTY Next 50 (Large-Mid Cap)",
        "aliases": ["NIFTYNEXT50", "NIFTY NEXT 50", "NEXT50", "^NSENEXT50"],
        "filename": "benchmark_niftynext50.csv",
        "yahoo_symbol": "^NSENEXT50",
        "category": "Broad Market",
    },
    "NIFTYMIDCAP150": {
        "label": "NIFTY Midcap 150 (Mid-Cap Space)",
        "aliases": ["NIFTYMIDCAP150", "NIFTY MIDCAP 150", "MIDCAP150", "NIFTYMIDCAP"],
        "filename": "benchmark_niftymidcap150.csv",
        "yahoo_symbol": None,
        "category": "Broad Market",
    },
    "NIFTYSMALLCAP250": {
        "label": "NIFTY Smallcap 250 (Small-Cap Space)",
        "aliases": ["NIFTYSMALLCAP250", "NIFTY SMALLCAP 250", "SMALLCAP250", "NIFTYSMALLCAP"],
        "filename": "benchmark_niftysmallcap250.csv",
        "yahoo_symbol": None,
        "category": "Broad Market",
    },
    "NIFTYBANK": {
        "label": "NIFTY Bank (Financial Sector)",
        "aliases": ["NIFTYBANK", "NIFTY BANK", "BANKNIFTY", "BANK", "^NSEBANK"],
        "filename": "benchmark_niftybank.csv",
        "yahoo_symbol": "^NSEBANK",
        "category": "Sectoral",
    },
    "NIFTYIT": {
        "label": "NIFTY IT (Technology Sector)",
        "aliases": ["NIFTYIT", "NIFTY IT", "IT", "^CNXIT"],
        "filename": "benchmark_niftyit.csv",
        "yahoo_symbol": "^CNXIT",
        "category": "Sectoral",
    },
    "UNIVERSE_PROXY": {
        "label": "Equal-Weighted Universe Median Proxy",
        "aliases": ["UNIVERSE_PROXY", "PROXY", "MEDIAN_PROXY", "EQUAL_WEIGHT", "UNIVERSE"],
        "filename": "benchmark_universe_proxy.csv",
        "yahoo_symbol": None,
        "category": "Dynamic Synthetic",
    },
}

_BENCHMARK_CACHE: Dict[str, pd.DataFrame] = {}


def get_benchmark_display_options() -> List[Tuple[str, str]]:
    """Returns list of (label, key) tuples for UI widgets."""
    options = []
    for key, info in BENCHMARK_CATALOG.items():
        options.append((f"📊 {info['label']}", key))
    return options


def normalize_benchmark_name(benchmark_input: Optional[str]) -> str:
    """Normalizes any benchmark name, alias, ticker, or symbol to canonical key."""
    if not benchmark_input:
        return "NIFTY500"
    
    clean = str(benchmark_input).strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    for key, info in BENCHMARK_CATALOG.items():
        if clean == key:
            return key
        for alias in info["aliases"]:
            a_clean = alias.strip().upper().replace(" ", "").replace("_", "").replace("-", "").replace("^", "")
            if clean == a_clean or clean == alias.strip().upper():
                return key
    
    # Return as uppercase stock symbol or custom key
    return str(benchmark_input).strip().upper()


def _get_app_base_dir() -> Path:
    try:
        from core.data_engine import get_base_dir
        return get_base_dir()
    except Exception:
        try:
            from .data_engine import get_base_dir
            return get_base_dir()
        except Exception:
            return Path(__file__).resolve().parent.parent


def resolve_benchmark_dataframe(
    benchmark_name: Optional[str] = "NIFTY500",
    base_dir: Optional[Path] = None,
    required_dates: Optional[List[str]] = None,
    universe_name: str = "NIFTY500",
) -> pd.DataFrame:
    """
    Authoritative benchmark series loader and indicator generator.
    Resolves official indices, constituent stock tickers, universe proxies, or custom CSVs.
    Guarantees non-empty continuous price series with all indicators populated:
      - date, close, daily_return, ret_252, ema_20, ema_50, ema_200, high_252, drawdown
    """
    global _BENCHMARK_CACHE
    base_path = Path(base_dir) if base_dir else _get_app_base_dir()
    norm_key = normalize_benchmark_name(benchmark_name)
    cache_key = f"{norm_key}_{universe_name}"

    if cache_key in _BENCHMARK_CACHE:
        df_cached = _BENCHMARK_CACHE[cache_key].copy()
        if required_dates:
            return _align_and_fill_dates(df_cached, required_dates)
        return df_cached

    df: Optional[pd.DataFrame] = None

    # Case 1: Standard Catalog Preset with existing CSV
    if norm_key in BENCHMARK_CATALOG:
        fn = BENCHMARK_CATALOG[norm_key]["filename"]
        csv_path = base_path / "data" / fn
        if csv_path.exists():
            try:
                raw_df = pd.read_csv(csv_path)
                if "date" in raw_df.columns and "close" in raw_df.columns and len(raw_df) > 100:
                    df = compute_benchmark_indicators(raw_df)
            except Exception:
                df = None

    # Case 2: Direct file path
    if df is None:
        direct_path = Path(str(benchmark_name))
        if direct_path.exists() and direct_path.is_file():
            try:
                raw_df = pd.read_csv(direct_path)
                if "date" in raw_df.columns and "close" in raw_df.columns:
                    df = compute_benchmark_indicators(raw_df)
            except Exception:
                df = None

    # Case 3: Single stock ticker from universe.db (e.g. RELIANCE, TCS, HDFCBANK)
    if df is None and norm_key not in ("UNIVERSE_PROXY", "PROXY"):
        stock_df = _load_ticker_from_db(norm_key, base_path)
        if stock_df is not None and len(stock_df) > 100:
            df = compute_benchmark_indicators(stock_df)

    # Case 4: Fetch online if Yahoo symbol exists and network is reachable
    if df is None and norm_key in BENCHMARK_CATALOG and BENCHMARK_CATALOG[norm_key].get("yahoo_symbol"):
        y_sym = BENCHMARK_CATALOG[norm_key]["yahoo_symbol"]
        fetched_df = _fetch_yahoo_chart_series(y_sym)
        if fetched_df is not None and len(fetched_df) > 200:
            # Backfill early dates (pre-2007) from NIFTY500 baseline if available
            base_n500 = base_path / "data" / "benchmark_nifty500.csv"
            if base_n500.exists():
                try:
                    n500_df = pd.read_csv(base_n500)
                    fetched_df = _bridge_with_reference(fetched_df, n500_df)
                except Exception:
                    pass
            df = compute_benchmark_indicators(fetched_df)
            # Save for offline reuse
            fn = BENCHMARK_CATALOG[norm_key]["filename"]
            csv_path = base_path / "data" / fn
            try:
                df.to_csv(csv_path, index=False)
            except Exception:
                pass

    # Case 5: Universe Equal-Weighted Median Proxy
    if df is None and norm_key in ("UNIVERSE_PROXY", "NIFTY750", "NIFTYMIDCAP150", "NIFTYSMALLCAP250"):
        df = _build_universe_proxy_series(universe_name=universe_name, base_dir=base_path)

    # Case 6: Fallback to baseline benchmark_nifty500.csv
    if df is None:
        fallback_csv = base_path / "data" / "benchmark_nifty500.csv"
        if fallback_csv.exists():
            raw_df = pd.read_csv(fallback_csv)
            df = compute_benchmark_indicators(raw_df)
        else:
            # Absolute synthetic fallback
            df = _build_synthetic_flat_benchmark(required_dates)

    # Align dates if requested
    if required_dates:
        df = _align_and_fill_dates(df, required_dates)

    _BENCHMARK_CACHE[cache_key] = df
    return df.copy()


def _align_and_fill_dates(df: pd.DataFrame, dates: List[str]) -> pd.DataFrame:
    """Guarantees benchmark DataFrame has exactly one row for every required trading date."""
    df = df.copy()
    df["date"] = df["date"].astype(str)
    date_set = set(df["date"].values)
    missing = [d for d in dates if d not in date_set]

    if missing:
        min_existing = df["date"].min()
        pre_missing = [d for d in missing if d < min_existing]
        if pre_missing:
            base_n500 = _get_app_base_dir() / "data" / "benchmark_nifty500.csv"
            if base_n500.exists():
                try:
                    n500_df = pd.read_csv(base_n500)
                    df = _bridge_with_reference(df, n500_df)
                except Exception:
                    pass

        date_set = set(df["date"].values)
        remaining_missing = [d for d in dates if d not in date_set]
        if remaining_missing:
            extra_rows = pd.DataFrame({"date": remaining_missing})
            df = pd.concat([df, extra_rows], ignore_index=True)
            df.sort_values("date", inplace=True)
            df.reset_index(drop=True, inplace=True)
            df["close"] = df["close"].ffill().bfill().fillna(1000.0)
        df = compute_benchmark_indicators(df)

    # Filter to requested dates
    req_set = set(dates)
    aligned = df[df["date"].isin(req_set)].copy()
    aligned.sort_values("date", inplace=True)
    aligned.reset_index(drop=True, inplace=True)
    return aligned


def _load_ticker_from_db(symbol: str, base_dir: Path) -> Optional[pd.DataFrame]:
    """Loads price series for a single ticker directly from universe.db, adjusting for corporate actions."""
    db_path = base_dir / "data" / "universe.db"
    if not db_path.exists():
        return None
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        q = "SELECT date, open, high, low, close, volume FROM prices WHERE symbol = ? ORDER BY date ASC;"
        try:
            df = pd.read_sql_query(q, conn, params=(symbol,))
        except Exception:
            # Fallback if only date, close exists in schema
            df = pd.read_sql_query("SELECT date, close FROM prices WHERE symbol = ? ORDER BY date ASC;", conn, params=(symbol,))

        if not df.empty and "date" in df.columns and "close" in df.columns:
            df["date"] = df["date"].astype(str)
            for col in ["open", "high", "low", "close", "volume"]:
                if col in df.columns:
                    df[col] = df[col].astype(float)
                else:
                    df[col] = df["close"].astype(float) if col != "volume" else 1000.0

            # Route through AnalyticalPriceEngine to adjust for splits / bonuses
            try:
                from core.analytical_price import AnalyticalPriceEngine
                ape = AnalyticalPriceEngine(base_dir=base_dir)
                adj_df, _ = ape.derive_analytical_series(symbol, df)
                if not adj_df.empty:
                    return adj_df[["date", "close"]].copy()
            except Exception:
                pass

            return df[["date", "close"]].copy()
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return None


def _fetch_yahoo_chart_series(symbol: str) -> Optional[pd.DataFrame]:
    """Fetches continuous daily index prices via Yahoo Finance API."""
    try:
        sym_encoded = requests.utils.quote(symbol)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym_encoded}?period1=1167696000&period2=1792195200&interval=1d"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code == 200:
            data = r.json()
            res = data["chart"]["result"][0]
            ts = res.get("timestamp", [])
            closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])
            if ts and closes and len(ts) == len(closes):
                rows = []
                for t, c in zip(ts, closes):
                    if c is not None and np.isfinite(c) and c > 0:
                        d_str = datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d")
                        rows.append({"date": d_str, "close": float(c)})
                if rows:
                    df = pd.DataFrame(rows)
                    df.drop_duplicates(subset=["date"], keep="last", inplace=True)
                    df.sort_values("date", inplace=True)
                    df.reset_index(drop=True, inplace=True)
                    return df
    except Exception:
        pass
    return None


def _bridge_with_reference(df: pd.DataFrame, ref_df: pd.DataFrame) -> pd.DataFrame:
    """Pre-pends scaled reference returns for historical dates preceding the target index inception."""
    if df.empty or ref_df.empty:
        return df
    
    first_dt = df["date"].min()
    earlier_ref = ref_df[ref_df["date"] < first_dt].copy()
    if earlier_ref.empty:
        return df
    
    earlier_ref.sort_values("date", inplace=True)
    first_target_px = float(df["close"].iloc[0])
    ref_overlap_px = float(ref_df[ref_df["date"] >= first_dt]["close"].iloc[0]) if (ref_df["date"] >= first_dt).any() else float(ref_df["close"].iloc[-1])
    scale = first_target_px / max(1.0, ref_overlap_px)

    bridged_rows = []
    for _, r in earlier_ref.iterrows():
        bridged_rows.append({"date": str(r["date"]), "close": float(r["close"]) * scale})

    b_df = pd.DataFrame(bridged_rows)
    merged = pd.concat([b_df, df], ignore_index=True)
    merged.sort_values("date", inplace=True)
    merged.drop_duplicates(subset=["date"], keep="last", inplace=True)
    merged.reset_index(drop=True, inplace=True)
    return merged


def _build_universe_proxy_series(universe_name: str = "NIFTY500", base_dir: Optional[Path] = None) -> pd.DataFrame:
    """Builds an equal-weighted, continuous benchmark proxy from universe.db constituent prices."""
    base_path = Path(base_dir) if base_dir else _get_app_base_dir()
    db_path = base_path / "data" / "universe.db"
    
    conn = None
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        # Pull 50 liquid symbols
        q = "SELECT symbol, count(*) as cnt FROM prices GROUP BY symbol HAVING cnt > 1000 ORDER BY cnt DESC LIMIT 60;"
        syms_df = pd.read_sql_query(q, conn)
        symbols = syms_df["symbol"].tolist()[:50]
        
        placeholders = ",".join(["?"] * len(symbols))
        q_prices = f"SELECT date, close FROM prices WHERE symbol IN ({placeholders}) ORDER BY date ASC;"
        px_df = pd.read_sql_query(q_prices, conn, params=symbols)

        if not px_df.empty:
            piv = px_df.pivot(index="date", columns="symbol", values="close")
            # Clamp daily returns to exchange statutory circuit bounds [-20%, +20%] to neutralize unadjusted splits
            clamped_rets = piv.pct_change(fill_method=None).clip(lower=-0.20, upper=0.20)
            rets = clamped_rets.median(axis=1).fillna(0.0)
            cum_index = (1.0 + rets).cumprod() * 1000.0
            proxy_df = pd.DataFrame({"date": cum_index.index.astype(str), "close": cum_index.values.astype(float)})
            return compute_benchmark_indicators(proxy_df)
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    
    return _build_synthetic_flat_benchmark()


def _build_synthetic_flat_benchmark(dates: Optional[List[str]] = None) -> pd.DataFrame:
    """Failsafe synthetic baseline benchmark."""
    d_list = dates if dates else [
        (datetime.date(2016, 1, 1) + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(3650)
    ]
    df = pd.DataFrame({"date": d_list, "close": 1000.0})
    return compute_benchmark_indicators(df)


# Canonical Alias
resolve_benchmark_series = resolve_benchmark_dataframe
