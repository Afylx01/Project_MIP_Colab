"""
pydroid_core/scan_quality_report.py
Scan Quality, Lineage & Diagnostic Reporting Engine for Project MIP Pydroid3.
Produces machine-readable (scan_quality.json) and human-readable (scan_quality.md) artifacts.
"""

from collections import Counter
from dataclasses import dataclass, field
import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd

from .config import MIPScannerConfig
from .health import ScannerHealthReport, ScannerHealthState
from .reason_codes import ScannerReasonCode


@dataclass
class CandidateExplanation:
    """Individual security explanation record."""
    symbol: str
    security_id: str
    sector: str
    close: float
    high_252: float
    ema200: float
    rs_ratio: float
    rs_ema200: float
    ret_252: float
    vol_252: float
    volar_score: float
    rank: Optional[int]
    is_qualified: bool
    reason_code: str
    diagnostic_details: str
    bypassed_sector_cap: bool = False


class ScanQualityReporter:
    """
    Assembles execution lineage, reason-code distributions, and explainable signals.
    """

    def __init__(self, config: Optional[MIPScannerConfig] = None):
        self.config = config or MIPScannerConfig()

    def generate_report(
        self,
        as_of_date: str,
        universe_label: str,
        health_report: ScannerHealthReport,
        explanations: List[CandidateExplanation],
        reason_counts: Dict[str, int],
        benchmark_info: Dict[str, Any],
        runtime_seconds: float,
        scan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Assembles full scan quality data structure."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sid = scan_id or f"SCAN_{as_of_date}_{int(datetime.datetime.now().timestamp())}"

        qualified_count = sum(1 for c in explanations if c.is_qualified)
        rejected_count = len(explanations) - qualified_count

        return {
            "lineage": {
                "scan_id": sid,
                "timestamp": now_str,
                "as_of_date": as_of_date,
                "strategy_version": self.config.strategy_version,
                "scanner_version": self.config.scanner_version,
                "schema_version": self.config.schema_version,
                "config_hash": self.config.get_config_hash(),
                "runtime_seconds": round(runtime_seconds, 2),
            },
            "universe": {
                "universe_label": universe_label,
                "requested_symbols": health_report.requested_symbols,
                "processed_symbols": health_report.processed_symbols,
                "coverage_pct": round(health_report.coverage_pct, 2),
                "qualified_candidates": qualified_count,
                "rejected_candidates": rejected_count,
            },
            "health": health_report.to_dict(),
            "benchmark_regime": benchmark_info,
            "reason_code_distribution": reason_counts,
            "candidates": [
                {
                    "symbol": c.symbol,
                    "security_id": c.security_id,
                    "sector": c.sector,
                    "close": round(c.close, 2) if c.close else None,
                    "high_252": round(c.high_252, 2) if c.high_252 else None,
                    "ema200": round(c.ema200, 2) if c.ema200 else None,
                    "rs_ratio": round(c.rs_ratio, 4) if c.rs_ratio else None,
                    "ret_252": round(c.ret_252, 4) if c.ret_252 else None,
                    "volar_score": round(c.volar_score, 4) if c.volar_score else None,
                    "rank": c.rank,
                    "is_qualified": c.is_qualified,
                    "reason_code": c.reason_code,
                    "details": c.diagnostic_details,
                    "bypassed_sector_cap": c.bypassed_sector_cap,
                }
                for c in explanations
            ],
        }

    def export_json(self, report_data: Dict[str, Any], output_path: Path):
        """Exports scan quality report as JSON."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

    def export_markdown(self, report_data: Dict[str, Any], output_path: Path):
        """Exports human-readable Markdown scan quality report."""
        lin = report_data["lineage"]
        univ = report_data["universe"]
        hlth = report_data["health"]
        bm = report_data["benchmark_regime"]
        reasons = report_data["reason_code_distribution"]

        lines = [
            f"# Quantitative Scanner Quality & Lineage Report",
            f"",
            f"**Scan ID:** `{lin['scan_id']}`  ",
            f"**Execution Timestamp:** {lin['timestamp']}  ",
            f"**As-Of Market Date:** {lin['as_of_date']}  ",
            f"**Strategy Version:** `{lin['strategy_version']}`  ",
            f"**Scanner Version:** `{lin['scanner_version']}`  ",
            f"**Configuration Hash:** `{lin['config_hash'][:16]}...`  ",
            f"**Execution Runtime:** {lin['runtime_seconds']}s  ",
            f"",
            f"---",
            f"",
            f"## 1. Scanner Health State: **{hlth['state']}**",
            f"",
            f"- **Allow Actionable Buys:** `{hlth['allow_actionable_buys']}`",
            f"- **Universe Coverage:** {univ['coverage_pct']}% ({univ['processed_symbols']} / {univ['requested_symbols']} symbols)",
            f"- **Benchmark Status:** `{bm.get('status', 'UNKNOWN')}` (Regime: `{bm.get('regime', 'UNKNOWN')}`)",
        ]

        if hlth["reasons"]:
            lines.extend([f"", f"### Critical Health Blocking Reasons:"])
            for r in hlth["reasons"]:
                lines.append(f"- ⚠️ {r}")

        if hlth["warnings"]:
            lines.extend([f"", f"### Non-Critical Health Warnings:"])
            for w in hlth["warnings"]:
                lines.append(f"- ℹ️ {w}")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 2. Quantitative Funnel & Reason Code Distribution",
            f"",
            f"| Metric | Count | Percentage |",
            f"|---|---|---|",
            f"| **Requested Universe** | {univ['requested_symbols']} | 100.0% |",
            f"| **Data-Valid Securities** | {univ['processed_symbols']} | {univ['coverage_pct']}% |",
            f"| **Qualified Strategy Candidates** | {univ['qualified_candidates']} | {round(univ['qualified_candidates'] / max(1, univ['requested_symbols']) * 100, 1)}% |",
            f"| **Excluded / Failed Securities** | {univ['rejected_candidates']} | {round(univ['rejected_candidates'] / max(1, univ['requested_symbols']) * 100, 1)}% |",
            f"",
            f"### Reason Code Histogram:",
            f"",
            f"| Reason Code | Count | Category | Description |",
            f"|---|---|---|---|",
        ])

        for code_str, count in sorted(reasons.items(), key=lambda x: x[1], reverse=True):
            try:
                code_enum = ScannerReasonCode(code_str)
                cat = code_enum.category.value
                desc = code_enum.description
            except Exception:
                cat = "OTHER"
                desc = code_str
            lines.append(f"| `{code_str}` | {count} | {cat} | {desc} |")

        lines.extend([
            f"",
            f"---",
            f"",
            f"## 3. Top Qualified Candidates",
            f"",
            f"| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |",
            f"|---|---|---|---|---|---|---|---|---|",
        ])

        qualified = [c for c in report_data["candidates"] if c["is_qualified"] and c["rank"] is not None]
        qualified.sort(key=lambda x: x["rank"])
        for q in qualified[:25]:
            lines.append(
                f"| {q['rank']} | **{q['symbol']}** | {q['sector']} | ₹{q['close']:,.2f} | "
                f"`{q['volar_score']:.2f}` | {q['ret_252'] * 100:+.1f}% | PASS | PASS | PASS |"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")
