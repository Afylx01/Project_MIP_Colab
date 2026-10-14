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

from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import datetime
import math
import numpy as np
import pandas as pd


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
