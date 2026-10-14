"""
pydroid_core/reason_codes.py
Standardized Machine-Readable Diagnostic Reason Codes for Project MIP Pydroid3.
Provides structured diagnostic reporting for candidate qualification, exclusion, and data integrity.
"""

from enum import Enum
from typing import Dict


class ScannerReasonCategory(str, Enum):
    SUCCESS = "SUCCESS"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    HISTORY = "HISTORY"
    STRATEGY_FILTER = "STRATEGY_FILTER"
    BENCHMARK_REGIME = "BENCHMARK_REGIME"
    UNIVERSE = "UNIVERSE"
    RISK_AND_SIZING = "RISK_AND_SIZING"


class ScannerReasonCode(str, Enum):
    """
    Exhaustive taxonomy of machine-readable qualification and disqualification reason codes.
    """
    # Success State
    PASS = "PASS"

    # Data Integrity & Bar Validation
    INVALID_OHLC = "INVALID_OHLC"
    DUPLICATE_PRICE = "DUPLICATE_PRICE"
    STALE_PRICE = "STALE_PRICE"
    FUTURE_DATA_DETECTED = "FUTURE_DATA_DETECTED"
    CORPORATE_ACTION_INVALID = "CORPORATE_ACTION_INVALID"
    CORPORATE_ACTION_REVIEW_REQUIRED = "CORPORATE_ACTION_REVIEW_REQUIRED"
    UNRESOLVED_STRUCTURAL_PRICE_EVENT = "UNRESOLVED_STRUCTURAL_PRICE_EVENT"
    UNKNOWN_MATERIAL_EVENT = "UNKNOWN_MATERIAL_EVENT"
    CORPORATE_HISTORY_UNSAFE = "CORPORATE_HISTORY_UNSAFE"
    ANOMALY_UNRESOLVED = "ANOMALY_UNRESOLVED"

    # Observation History
    INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"

    # Strategy Filter Violations
    BELOW_52W_HIGH_THRESHOLD = "BELOW_52W_HIGH_THRESHOLD"   # Failed Filter 1 (Close < 0.80 * High_252)
    BELOW_EMA200 = "BELOW_EMA200"                           # Failed Filter 2 (Close <= EMA_200)
    RS_BELOW_EMA = "RS_BELOW_EMA"                           # Failed Filter 3 (RS <= RS_EMA_200)
    RS_INVALID = "RS_INVALID"                               # Filter 3 cannot be calculated
    NEGATIVE_MOMENTUM = "NEGATIVE_MOMENTUM"                 # Ret_252 <= 0 or Volar <= 0
    VOLATILITY_INVALID = "VOLATILITY_INVALID"               # Volatility is NaN or non-finite
    VOLAR_INVALID = "VOLAR_INVALID"                         # Volar score is NaN, inf, or non-finite

    # Benchmark & Regime
    MISSING_BENCHMARK = "MISSING_BENCHMARK"                 # Benchmark file/series missing
    STALE_BENCHMARK = "STALE_BENCHMARK"                     # Benchmark older than market calendar
    INVALID_BENCHMARK = "INVALID_BENCHMARK"                 # Benchmark contains NaN or corrupt prices
    DEFENSIVE_REGIME = "DEFENSIVE_REGIME"                   # Market in defensive cash shield mode

    # Universe & Listing Status
    UNIVERSE_INVALID = "UNIVERSE_INVALID"                   # Not an active constituent as of date
    DELISTED = "DELISTED"                                   # Security delisted prior to evaluation date

    # Portfolio & Sizing
    SECTOR_CAP_EXCEEDED = "SECTOR_CAP_EXCEEDED"             # Qualified but bypassed due to sector hard cap
    PORTFOLIO_CANDIDATE_UNSAFE = "PORTFOLIO_CANDIDATE_UNSAFE"   # Candidate blocked by portfolio safety firewall
    PORTFOLIO_RANK_EXCEEDED = "PORTFOLIO_RANK_EXCEEDED"         # Candidate rank exceeds top_n allocation threshold
    PORTFOLIO_BUFFER_RETAINED = "PORTFOLIO_BUFFER_RETAINED"     # Existing holding retained within exit buffer
    PORTFOLIO_BUFFER_EXCEEDED = "PORTFOLIO_BUFFER_EXCEEDED"     # Existing holding exceeded exit buffer rank threshold
    PORTFOLIO_DUPLICATE_CANDIDATE = "PORTFOLIO_DUPLICATE_CANDIDATE" # Duplicate candidate symbol or security ID
    PORTFOLIO_INVALID_PRICE = "PORTFOLIO_INVALID_PRICE"         # Candidate price is non-positive or non-finite
    PORTFOLIO_REGIME_BLOCKED = "PORTFOLIO_REGIME_BLOCKED"       # New entry blocked by defensive regime

    @property
    def category(self) -> ScannerReasonCategory:
        """Maps reason code to institutional diagnostic category."""
        if self == ScannerReasonCode.PASS:
            return ScannerReasonCategory.SUCCESS
        elif self in (
            ScannerReasonCode.INVALID_OHLC,
            ScannerReasonCode.DUPLICATE_PRICE,
            ScannerReasonCode.STALE_PRICE,
            ScannerReasonCode.FUTURE_DATA_DETECTED,
            ScannerReasonCode.CORPORATE_ACTION_INVALID,
            ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED,
            ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT,
            ScannerReasonCode.UNKNOWN_MATERIAL_EVENT,
            ScannerReasonCode.CORPORATE_HISTORY_UNSAFE,
            ScannerReasonCode.ANOMALY_UNRESOLVED,
        ):
            return ScannerReasonCategory.DATA_INTEGRITY
        elif self == ScannerReasonCode.INSUFFICIENT_HISTORY:
            return ScannerReasonCategory.HISTORY
        elif self in (
            ScannerReasonCode.BELOW_52W_HIGH_THRESHOLD,
            ScannerReasonCode.BELOW_EMA200,
            ScannerReasonCode.RS_BELOW_EMA,
            ScannerReasonCode.RS_INVALID,
            ScannerReasonCode.NEGATIVE_MOMENTUM,
            ScannerReasonCode.VOLATILITY_INVALID,
            ScannerReasonCode.VOLAR_INVALID,
        ):
            return ScannerReasonCategory.STRATEGY_FILTER
        elif self in (
            ScannerReasonCode.MISSING_BENCHMARK,
            ScannerReasonCode.STALE_BENCHMARK,
            ScannerReasonCode.INVALID_BENCHMARK,
            ScannerReasonCode.DEFENSIVE_REGIME,
        ):
            return ScannerReasonCategory.BENCHMARK_REGIME
        elif self in (
            ScannerReasonCode.UNIVERSE_INVALID,
            ScannerReasonCode.DELISTED,
        ):
            return ScannerReasonCategory.UNIVERSE
        else:
            return ScannerReasonCategory.RISK_AND_SIZING

    @property
    def description(self) -> str:
        """Institutional description of reason code."""
        descriptions: Dict[ScannerReasonCode, str] = {
            ScannerReasonCode.PASS: "Candidate fully qualified and verified across all strategy rules.",
            ScannerReasonCode.INVALID_OHLC: "OHLCV prices corrupted, non-positive, zero, NaN, or geometrically impossible.",
            ScannerReasonCode.DUPLICATE_PRICE: "Conflicting duplicate price bars detected on the same trading session.",
            ScannerReasonCode.STALE_PRICE: "Security price series is stale relative to the active trading calendar.",
            ScannerReasonCode.FUTURE_DATA_DETECTED: "Lookahead bias violation: bar date exceeds simulation as-of date.",
            ScannerReasonCode.CORPORATE_ACTION_INVALID: "Corporate action ex-date violates temporal causality.",
            ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED: "Material corporate reorganization requires review; unadjusted or unverified factor.",
            ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT: "Unresolved structural price discontinuity (drop >= 40% or jump >= 60%) in lookback window.",
            ScannerReasonCode.UNKNOWN_MATERIAL_EVENT: "Unknown material corporate event detected; history cannot be verified.",
            ScannerReasonCode.CORPORATE_HISTORY_UNSAFE: "Historical price series is contaminated by an unadjusted reorganization event.",
            ScannerReasonCode.ANOMALY_UNRESOLVED: "Unexplained market data dislocation (flash crash or extreme price jump).",
            ScannerReasonCode.INSUFFICIENT_HISTORY: "History is below mandatory 252-session minimum.",
            ScannerReasonCode.BELOW_52W_HIGH_THRESHOLD: "Close is below 80% of 52-week rolling high.",
            ScannerReasonCode.BELOW_EMA200: "Close is not strictly above the 200-day exponential moving average.",
            ScannerReasonCode.RS_BELOW_EMA: "Relative strength vs benchmark is below its 200-day EMA.",
            ScannerReasonCode.RS_INVALID: "Relative strength cannot be computed due to benchmark issues.",
            ScannerReasonCode.NEGATIVE_MOMENTUM: "1-year momentum return or Volar score is non-positive.",
            ScannerReasonCode.VOLATILITY_INVALID: "Annualized volatility is NaN, infinite, or non-finite.",
            ScannerReasonCode.VOLAR_INVALID: "Volar risk-adjusted momentum score is NaN, infinite, or non-finite.",
            ScannerReasonCode.MISSING_BENCHMARK: "NIFTY 500 benchmark series is missing from repository.",
            ScannerReasonCode.STALE_BENCHMARK: "Benchmark series is stale relative to current trading calendar.",
            ScannerReasonCode.INVALID_BENCHMARK: "Benchmark series contains NaN, corrupt, or zero values.",
            ScannerReasonCode.DEFENSIVE_REGIME: "Market regime is defensive; equity entries restricted.",
            ScannerReasonCode.UNIVERSE_INVALID: "Security was not an active constituent of universe on date.",
            ScannerReasonCode.DELISTED: "Security was delisted on or prior to evaluation date.",
            ScannerReasonCode.SECTOR_CAP_EXCEEDED: "Candidate qualified for strategy but bypassed due to sector hard cap.",
            ScannerReasonCode.PORTFOLIO_CANDIDATE_UNSAFE: "Candidate blocked by downstream portfolio safety firewall.",
            ScannerReasonCode.PORTFOLIO_RANK_EXCEEDED: "Candidate rank exceeds top_n allocation threshold for new entries.",
            ScannerReasonCode.PORTFOLIO_BUFFER_RETAINED: "Existing holding retained within exit buffer rank threshold.",
            ScannerReasonCode.PORTFOLIO_BUFFER_EXCEEDED: "Existing holding exceeded exit buffer rank threshold and liquidated.",
            ScannerReasonCode.PORTFOLIO_DUPLICATE_CANDIDATE: "Duplicate candidate symbol or canonical security ID rejected.",
            ScannerReasonCode.PORTFOLIO_INVALID_PRICE: "Candidate price is non-positive, NaN, or non-finite.",
            ScannerReasonCode.PORTFOLIO_REGIME_BLOCKED: "New candidate entry blocked due to defensive benchmark regime.",
        }
        return descriptions.get(self, "Unknown status code.")
