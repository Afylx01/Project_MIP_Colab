"""
pydroid_core/health.py
Scanner Health Governance & Degradation Monitoring Engine for Project MIP Pydroid3.
Enforces explicit HEALTHY, DEGRADED, and BLOCKED state machine.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from .config import MIPScannerConfig


class ScannerHealthState(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"


@dataclass
class ScannerHealthReport:
    """Immutable health verdict of a scanner execution."""
    state: ScannerHealthState
    allow_actionable_buys: bool
    requested_symbols: int
    processed_symbols: int
    rejected_symbols: int
    coverage_pct: float
    benchmark_status: str
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "allow_actionable_buys": self.allow_actionable_buys,
            "requested_symbols": self.requested_symbols,
            "processed_symbols": self.processed_symbols,
            "rejected_symbols": self.rejected_symbols,
            "coverage_pct": round(self.coverage_pct, 2),
            "benchmark_status": self.benchmark_status,
            "reasons": self.reasons,
            "warnings": self.warnings,
        }


class ScannerHealthMonitor:
    """
    Evaluates execution completeness, data coverage, and benchmark state.
    Guarantees no silent degradation and blocks BUY signals when compromised.
    """

    def __init__(self, config: Optional[MIPScannerConfig] = None):
        self.config = config or MIPScannerConfig()

    def evaluate_health(
        self,
        requested_count: int,
        processed_count: int,
        benchmark_status: str,
        unresolved_anomalies_count: int = 0,
        critical_errors: Optional[List[str]] = None,
    ) -> ScannerHealthReport:
        """
        Determines overall scanner health status.
        Rules:
        - If benchmark is INVALID, STALE, or UNAVAILABLE -> Strictly BLOCKED.
        - If coverage < degraded threshold (75%) -> Strictly BLOCKED.
        - If coverage < healthy threshold (90%) -> DEGRADED.
        - If unresolved anomalies > 0 -> DEGRADED.
        - Otherwise -> HEALTHY.
        """
        reasons = list(critical_errors) if critical_errors else []
        warnings = []

        if requested_count <= 0:
            reasons.append("No symbols requested in universe.")
            return ScannerHealthReport(
                state=ScannerHealthState.BLOCKED,
                allow_actionable_buys=False,
                requested_symbols=0,
                processed_symbols=0,
                rejected_symbols=0,
                coverage_pct=0.0,
                benchmark_status=benchmark_status,
                reasons=reasons,
            )

        coverage = (processed_count / requested_count) * 100.0
        rejected_count = max(0, requested_count - processed_count)

        # Rule 1: Benchmark Failure -> Strictly BLOCKED
        bench_upper = str(benchmark_status).upper()
        if bench_upper in ("INVALID", "STALE", "UNAVAILABLE", "CORRUPT"):
            reasons.append(f"Benchmark integrity failure: status is {bench_upper}")

        # Rule 2: Coverage below degraded threshold (< 75%) -> Strictly BLOCKED
        if (coverage / 100.0) < self.config.degraded_coverage_threshold:
            reasons.append(
                f"Severe universe coverage loss: {coverage:.1f}% is below minimum {self.config.degraded_coverage_threshold * 100:.0f}% threshold"
            )

        # Evaluate BLOCKED state
        if reasons:
            return ScannerHealthReport(
                state=ScannerHealthState.BLOCKED,
                allow_actionable_buys=False,
                requested_symbols=requested_count,
                processed_symbols=processed_count,
                rejected_symbols=rejected_count,
                coverage_pct=coverage,
                benchmark_status=benchmark_status,
                reasons=reasons,
                warnings=warnings,
            )

        # Rule 3: Coverage between 75% and 90% -> DEGRADED
        if (coverage / 100.0) < self.config.healthy_coverage_threshold:
            warnings.append(
                f"Degraded universe coverage: {coverage:.1f}% is below standard {self.config.healthy_coverage_threshold * 100:.0f}% threshold"
            )

        # Rule 4: Unresolved anomalies present -> DEGRADED
        if unresolved_anomalies_count > 0:
            warnings.append(
                f"{unresolved_anomalies_count} unverified market data anomalies flagged during scan"
            )

        state = ScannerHealthState.DEGRADED if warnings else ScannerHealthState.HEALTHY
        return ScannerHealthReport(
            state=state,
            allow_actionable_buys=True,
            requested_symbols=requested_count,
            processed_symbols=processed_count,
            rejected_symbols=rejected_count,
            coverage_pct=coverage,
            benchmark_status=benchmark_status,
            reasons=reasons,
            warnings=warnings,
        )
