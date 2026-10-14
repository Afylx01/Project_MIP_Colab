"""
pydroid_core/config.py
Canonical Centralized Strategy Configuration & Governance Engine for Project MIP Pydroid3.
Eliminates magic numbers across scanner, backtester, and portfolio components.
"""

from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Dict, Any


@dataclass(frozen=True)
class MIPScannerConfig:
    """
    Canonical, immutable configuration container for MIP-Scanner-1.0.
    Provides deterministic SHA-256 configuration hashing for full data lineage.
    """
    # Strategy & Engine Versions
    strategy_version: str = "MIP-Scanner-1.0"
    scanner_version: str = "2.0.0-institutional"
    schema_version: str = "1.0.0"

    # Momentum Factor Parameters
    momentum_lookback_bars: int = 252         # Annual momentum lookback (Return_252)
    volatility_lookback_bars: int = 252       # Annualized volatility lookback
    volatility_floor: float = 0.05            # Minimum volatility denominator (5%)
    rolling_high_bars: int = 252              # 52-week rolling high window
    rolling_low_bars: int = 252               # 52-week rolling low window

    # Trend & Relative Strength Parameters
    ema_trend_span: int = 200                 # Stock trend EMA span
    ema_rs_span: int = 200                    # Relative strength EMA span
    ema_regime_span: int = 20                 # Benchmark market regime EMA span
    ema_intermediate_span: int = 50           # Intermediate trend EMA span
    atr_period: int = 14                      # Average True Range lookback
    retrace_threshold: float = 0.80           # Filter 1 threshold: Close >= 80% of 52w High

    # Minimum History Safeguards (Anti-IPO Protection)
    min_history_bars: int = 252               # Hard minimum observations for factor calculation
    min_history_ema: int = 200                # Hard minimum observations for 200 EMA
    min_history_volatility: int = 252         # Hard minimum observations for Volar

    # Risk Management & Portfolio Construction
    top_n_candidates: int = 20                # Target candidate pool size
    max_per_sector: int = 2                   # Anti-clustering hard cap per sector
    exit_buffer_rank: int = 40                # Rebalance retention buffer rank
    atr_stop_multiplier: float = 2.0          # Stop loss multiplier: Close - 2.0 * ATR
    nominal_portfolio_capital: float = 100000.0  # Standard ₹1 Lakh sizing unit
    risk_budget_pct: float = 0.01             # 1% capital risk per trade

    # Operational & Data Integrity Thresholds
    lookback_calendar_days: int = 550         # Database query lookback window
    max_tolerated_staleness_sessions: int = 2 # Max sessions behind calendar before marking STALE
    healthy_coverage_threshold: float = 0.90  # >= 90% processed universe required for HEALTHY
    degraded_coverage_threshold: float = 0.75 # >= 75% required before marking BLOCKED

    # Anomaly Detection & Structural Price Integrity Thresholds
    anomaly_price_jump_upper: float = 10.0    # 10x single-session price jump
    anomaly_price_drop_lower: float = 0.10    # 90% single-session price collapse (0.1x)
    anomaly_volume_multiple: float = 50.0     # 50x 30d median volume spike
    structural_price_drop_threshold: float = 0.60  # Drop >= 40% in single session (unexplained demerger/collapse)
    structural_price_jump_threshold: float = 1.60  # Jump >= 60% in single session (unexplained consolidation/reorg)
    structural_gap_threshold: float = 0.40         # Overnight open gap >= 40%
    statistical_anomaly_sigma: float = 6.0         # 6-sigma return dislocation
    min_reorganization_clean_sessions: int = 252   # Sessions required post-reorganization before window is clean

    def validate(self) -> None:
        """Validates configuration parameters against mathematical and logical invariants."""
        assert self.momentum_lookback_bars > 0, "momentum_lookback_bars must be > 0"
        assert self.volatility_floor > 0.0, "volatility_floor must be strictly positive"
        assert 0.0 < self.retrace_threshold <= 1.0, "retrace_threshold must be in (0, 1]"
        assert self.max_per_sector >= 1, "max_per_sector must be >= 1"
        assert self.top_n_candidates >= 1, "top_n_candidates must be >= 1"
        assert self.min_history_bars >= self.momentum_lookback_bars, "min_history_bars must cover momentum window"
        assert 0.0 < self.degraded_coverage_threshold <= self.healthy_coverage_threshold <= 1.0, "Coverage thresholds invalid"
        assert 0.0 < self.structural_price_drop_threshold < 1.0, "structural_price_drop_threshold must be in (0, 1)"
        assert self.structural_price_jump_threshold > 1.0, "structural_price_jump_threshold must be > 1.0"
        assert self.min_reorganization_clean_sessions >= self.momentum_lookback_bars, "Clean sessions must cover momentum window"

    def to_dict(self) -> Dict[str, Any]:
        """Serializes configuration to standard dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MIPScannerConfig":
        """Instantiates and validates configuration from dictionary."""
        cfg = cls(**data)
        cfg.validate()
        return cfg

    def get_config_hash(self) -> str:
        """
        Computes a deterministic SHA-256 fingerprint of the configuration object.
        Ensures audit traceability across every generated scan.
        """
        sorted_json = json.dumps(self.to_dict(), sort_keys=True, indent=None)
        return hashlib.sha256(sorted_json.encode("utf-8")).hexdigest()

    def __repr__(self) -> str:
        return f"MIPScannerConfig(strategy={self.strategy_version}, hash={self.get_config_hash()[:12]})"
