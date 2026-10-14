"""
pydroid_core/validation.py
Dedicated Quantitative Scanner Data Validation & Integrity Gate for Project MIP Pydroid3.
Enforces strict OHLCV consistency, duplicate classification, anti-staleness, and calendar alignment.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import datetime
import numpy as np
import pandas as pd

from .config import MIPScannerConfig
from .reason_codes import ScannerReasonCode


@dataclass
class ValidationResult:
    """Result of security bar data validation."""
    is_valid: bool
    reason_code: ScannerReasonCode
    message: str
    cleaned_df: Optional[pd.DataFrame] = None
    observation_count: int = 0
    staleness_sessions: int = 0
    latest_bar_date: Optional[str] = None
    expected_market_date: Optional[str] = None
    duplicate_count: int = 0


class ScannerDataValidator:
    """
    Institutional Data Integrity Gate for Quantitative Momentum Scanner.
    Validates every security prior to factor computation.
    """

    def __init__(
        self,
        config: Optional[MIPScannerConfig] = None,
        trading_calendar: Optional[List[str]] = None,
    ):
        self.config = config or MIPScannerConfig()
        self.trading_calendar = sorted(trading_calendar) if trading_calendar else []

    def get_expected_market_date(self, as_of_date: str) -> str:
        """Resolves the expected latest trading date on or before as_of_date."""
        as_of_clean = str(as_of_date).strip()[:10]
        if self.trading_calendar:
            valid_sessions = [d for d in self.trading_calendar if d <= as_of_clean]
            if valid_sessions:
                return valid_sessions[-1]

        # Fallback to weekday arithmetic
        try:
            dt = datetime.datetime.strptime(as_of_clean, "%Y-%m-%d").date()
            if dt.weekday() == 5:    # Saturday -> Friday
                expected_dt = dt - datetime.timedelta(days=1)
            elif dt.weekday() == 6:  # Sunday -> Friday
                expected_dt = dt - datetime.timedelta(days=2)
            else:
                expected_dt = dt
            return expected_dt.strftime("%Y-%m-%d")
        except Exception:
            return as_of_clean

    def validate_security_bars(
        self,
        symbol: str,
        df: pd.DataFrame,
        as_of_date: str,
    ) -> ValidationResult:
        """
        Validates historical bar series for a security:
        - Non-empty dataframe
        - Schema completeness
        - Anti-lookahead future date rejection
        - Positive, non-zero prices (O, H, L, C > 0, V >= 0)
        - Strict bar geometric consistency (H >= L, H >= O, H >= C, L <= O, L <= C)
        - Duplicate detection (Identical vs Conflicting)
        - Staleness check relative to trading calendar
        - Minimum observation history check (Anti-IPO protection)
        """
        as_of_clean = str(as_of_date).strip()[:10]
        expected_date = self.get_expected_market_date(as_of_clean)

        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"No price bars found for symbol {symbol}",
                expected_market_date=expected_date,
            )

        # 1. Schema Check
        required_cols = {"date", "open", "high", "low", "close", "volume"}
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"Missing required columns: {sorted(missing_cols)}",
                expected_market_date=expected_date,
            )

        df_work = df.copy()
        df_work["date"] = df_work["date"].astype(str).str.strip()

        # 2. Anti-Lookahead: Future Date Check
        future_mask = df_work["date"] > as_of_clean
        if future_mask.any():
            future_dates = df_work.loc[future_mask, "date"].tolist()[:3]
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.FUTURE_DATA_DETECTED,
                message=f"Lookahead violation: {len(future_dates)} bars with date > as_of_date {as_of_clean} (dates: {future_dates})",
                expected_market_date=expected_date,
            )

        df_work = df_work[df_work["date"] <= as_of_clean].copy()
        if df_work.empty:
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"No bars on or before {as_of_clean}",
                expected_market_date=expected_date,
            )

        # 3. Numeric Conversion & Missing Values
        numeric_cols = ["open", "high", "low", "close", "volume"]
        for col in numeric_cols:
            df_work[col] = pd.to_numeric(df_work[col], errors="coerce")

        if df_work[numeric_cols].isna().any().any():
            nan_counts = df_work[numeric_cols].isna().sum().to_dict()
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"Null or NaN values detected in OHLCV columns: {nan_counts}",
                expected_market_date=expected_date,
            )

        # 4. Strict Positivity & Geometric Bar Consistency
        price_invalid = (
            (df_work["open"] <= 0) |
            (df_work["high"] <= 0) |
            (df_work["low"] <= 0) |
            (df_work["close"] <= 0) |
            (df_work["volume"] < 0) |
            np.isinf(df_work["open"]) |
            np.isinf(df_work["high"]) |
            np.isinf(df_work["low"]) |
            np.isinf(df_work["close"])
        )
        if price_invalid.any():
            bad_count = int(price_invalid.sum())
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"{bad_count} bars contain non-positive, zero, or infinite OHLCV values",
                expected_market_date=expected_date,
            )

        # Impossible Bar Invariants
        impossible_bars = (
            (df_work["high"] < df_work["low"]) |
            (df_work["high"] < df_work["open"]) |
            (df_work["high"] < df_work["close"]) |
            (df_work["low"] > df_work["open"]) |
            (df_work["low"] > df_work["close"])
        )
        if impossible_bars.any():
            bad_count = int(impossible_bars.sum())
            bad_dates = df_work.loc[impossible_bars, "date"].tolist()[:3]
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INVALID_OHLC,
                message=f"{bad_count} geometrically impossible bars detected (dates: {bad_dates})",
                expected_market_date=expected_date,
            )

        # 5. Duplicate Detection (Identical vs Conflicting)
        dup_mask = df_work["date"].duplicated(keep=False)
        dup_count = int(df_work["date"].duplicated().sum())
        if dup_mask.any():
            dup_dates = df_work.loc[dup_mask, "date"].unique()
            for d in dup_dates:
                sub = df_work[df_work["date"] == d]
                diffs = (sub[numeric_cols] != sub[numeric_cols].iloc[0]).any().any()
                if diffs:
                    return ValidationResult(
                        is_valid=False,
                        reason_code=ScannerReasonCode.DUPLICATE_PRICE,
                        message=f"Conflicting duplicate price bars detected on session {d}",
                        expected_market_date=expected_date,
                        duplicate_count=dup_count,
                    )
            # Deterministic deduplication of identical bars
            df_work = df_work.drop_duplicates(subset=["date"], keep="first").copy()

        # 6. Chronological Sorting
        df_work = df_work.sort_values("date").reset_index(drop=True)
        latest_bar_date = str(df_work["date"].iloc[-1])

        # 7. Security Staleness Check
        staleness_sessions = 0
        if latest_bar_date < expected_date:
            if self.trading_calendar:
                missing_sessions = [d for d in self.trading_calendar if latest_bar_date < d <= expected_date]
                staleness_sessions = len(missing_sessions)
            else:
                try:
                    d_latest = datetime.datetime.strptime(latest_bar_date, "%Y-%m-%d").date()
                    d_exp = datetime.datetime.strptime(expected_date, "%Y-%m-%d").date()
                    staleness_sessions = max(0, (d_exp - d_latest).days)
                except Exception:
                    staleness_sessions = 1

            if staleness_sessions > self.config.max_tolerated_staleness_sessions:
                return ValidationResult(
                    is_valid=False,
                    reason_code=ScannerReasonCode.STALE_PRICE,
                    message=f"Security data stale: latest date {latest_bar_date} is {staleness_sessions} sessions behind expected {expected_date}",
                    latest_bar_date=latest_bar_date,
                    expected_market_date=expected_date,
                    staleness_sessions=staleness_sessions,
                    observation_count=len(df_work),
                )

        # 8. Minimum Observation History Check (Anti-IPO Protection)
        observation_count = len(df_work)
        if observation_count < self.config.min_history_bars:
            return ValidationResult(
                is_valid=False,
                reason_code=ScannerReasonCode.INSUFFICIENT_HISTORY,
                message=f"Insufficient history: {observation_count} sessions < {self.config.min_history_bars} required",
                latest_bar_date=latest_bar_date,
                expected_market_date=expected_date,
                observation_count=observation_count,
            )

        # All validation gates passed
        return ValidationResult(
            is_valid=True,
            reason_code=ScannerReasonCode.PASS,
            message="Data integrity fully verified.",
            cleaned_df=df_work,
            observation_count=observation_count,
            staleness_sessions=staleness_sessions,
            latest_bar_date=latest_bar_date,
            expected_market_date=expected_date,
            duplicate_count=dup_count,
        )
