#!/usr/bin/env python3
"""
MIP Android — Fail-Closed Alert & Telegram Notification Dispatcher
Phase 42: Automated notification formatting, deliverable digest, and fail-safe Telegram dispatch.

Reads:
- reports/pipeline_telemetry.json
- reports/operational_health.json
- reports/screener_output_live.csv

Dispatches:
- Concise institutional Telegram alert payload.
- Fails gracefully if unconfigured or offline, logging audit record to reports/alert_dispatch.json.
"""

import os
import sys
import json
import argparse
import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.telegram_sender import PydroidTelegramSender


class AlertDispatcher:
    """Institutional alert formatting and Telegram dispatcher for Project MIP."""

    def __init__(self, base_dir: Path = PROJECT_ROOT, reports_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir)
        self.reports_dir = Path(reports_dir) if reports_dir is not None else self.base_dir / "reports"
        self.telemetry_path = self.reports_dir / "pipeline_telemetry.json"
        self.health_path = self.reports_dir / "operational_health.json"
        self.screener_path = self.reports_dir / "screener_output_live.csv"
        self.dispatch_log_path = self.reports_dir / "alert_dispatch.json"
        self.telegram_sender = PydroidTelegramSender()

    def format_alert_payload(self) -> str:
        """Assembles institutional markdown summary from production report artifacts."""
        # 1. Load telemetry
        telemetry = {}
        if self.telemetry_path.exists():
            try:
                telemetry = json.loads(self.telemetry_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # 2. Load health
        health = {}
        if self.health_path.exists():
            try:
                health = json.loads(self.health_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        target_date = telemetry.get("as_of_date", datetime.date.today().isoformat())
        universe = telemetry.get("universe_label", telemetry.get("universe_mode", "NIFTY 500"))
        runtime = telemetry.get("runtime_seconds", 0.0)
        peak_ram = telemetry.get("peak_memory_mb", 0.0)
        pipeline_status = telemetry.get("pipeline_status", "UNKNOWN")

        health_status = health.get("overall_health", "UNKNOWN")
        checks_passed = health.get("checks_passed", 0)
        checks_total = health.get("checks_total", 0)

        lines = [
            f"<b>🚀 Project MIP Momentum Scanner Alert</b>",
            f"<b>Target Date:</b> {target_date} | <b>Universe:</b> {universe}",
            f"<b>Status:</b> {pipeline_status} (⏱️ {runtime}s | 💾 {peak_ram} MB RSS)",
            f"<b>Operational Health:</b> {health_status} ({checks_passed}/{checks_total} checks verified)",
        ]

        # 3. Load screener candidates
        if self.screener_path.exists():
            try:
                df = pd.read_csv(self.screener_path)
                allow_buy = bool(df["allow_buy"].any()) if not df.empty and "allow_buy" in df.columns else False
                regime_label = "BULLISH (Buys Permitted)" if allow_buy else "DEFENSIVE / BEAR (0 Buys Authorized)"
                lines.append(f"<b>Market Regime:</b> {regime_label}")

                # Top 5 candidates
                top5 = df.head(5)
                lines.append("\n<b>Top Momentum Candidates (Max 2/Sector Enforced):</b>")
                for idx, (_, r) in enumerate(top5.iterrows(), 1):
                    sym = r.get("symbol", "N/A")
                    sector = r.get("sector", "N/A")
                    volar = round(float(r.get("volar_score", 0.0)), 2)
                    ret_1y = round(float(r.get("ret_252", 0.0)) * 100, 1) if "ret_252" in r else "N/A"
                    stop = round(float(r.get("stop_loss", 0.0)), 2)
                    tier = r.get("selection_tier", "TIER-3")
                    lines.append(
                        f"{idx}. <b>{sym}</b> ({sector}) | Volar: {volar} | 1Y: {ret_1y}% | SL: ₹{stop} | {tier}"
                    )
            except Exception as e:
                lines.append(f"<b>Candidate Parsing Notice:</b> {e}")
        else:
            lines.append("<i>Candidate screener file not found.</i>")

        return "\n".join(lines)

    def dispatch(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Dispatches alert to Telegram.
        Fails safely if unconfigured, offline, or network error occurs.
        Logs dispatch status record to reports/alert_dispatch.json.
        """
        payload = self.format_alert_payload()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "dispatched_at": now_iso,
            "dry_run": dry_run,
            "status": "PENDING",
            "payload_length": len(payload),
        }

        if dry_run:
            record["status"] = "DRY_RUN_SUCCESS"
            record["message"] = "Simulated dispatch completed cleanly."
        elif not self.telegram_sender.is_configured():
            record["status"] = "SKIPPED_UNCONFIGURED"
            record["message"] = "Telegram credentials unset; dispatch safely bypassed."
        else:
            try:
                # Attempt dispatch
                success = self.telegram_sender.send_message(payload, parse_mode="HTML")
                if success:
                    record["status"] = "SENT_SUCCESS"
                    record["message"] = "Telegram notification delivered."
                else:
                    record["status"] = "SEND_FAILED"
                    record["message"] = "Telegram API responded with failure."
            except Exception as e:
                record["status"] = "OFFLINE_FAILED"
                record["message"] = f"Dispatch failed gracefully: {str(e)}"

        # Save dispatch audit log
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        with open(self.dispatch_log_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        return record

    def format_critical_health_alert(self, health_summary: Dict[str, Any]) -> str:
        """Formats high-priority notification for pre-flight health check failure."""
        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        failed_checks = health_summary.get("failed_checks", [])
        passed = health_summary.get("checks_passed", 0)
        total = health_summary.get("checks_total", 0)
        overall = health_summary.get("overall_health", "UNHEALTHY")

        lines = [
            "🚨 <b>CRITICAL OPERATIONAL ALERT: Health Check Failed</b>",
            f"<b>Timestamp:</b> {now_str}",
            f"<b>Status:</b> <b>{overall}</b> ({passed}/{total} checks passed)",
            "",
            "<b>Failed Safeguards:</b>",
        ]
        if failed_checks:
            for fc in failed_checks:
                lines.append(f"  • ❌ <b>{fc}</b>")
        else:
            lines.append("  • ❌ <i>Pre-flight operational gate reported degraded health.</i>")

        lines.extend([
            "",
            "<b>Action:</b> Downstream momentum scan halted to protect data integrity.",
            "<b>Resolution:</b> Investigate operational health logs at reports/operational_health.json."
        ])
        return "\n".join(lines)

    def dispatch_health_failure(self, health_summary: Dict[str, Any], dry_run: bool = False) -> Dict[str, Any]:
        """Dispatches emergency notification when pre-flight health check fails."""
        payload = self.format_critical_health_alert(health_summary)
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        record = {
            "dispatched_at": now_iso,
            "type": "CRITICAL_HEALTH_FAILURE",
            "dry_run": dry_run,
            "status": "PENDING",
            "payload_length": len(payload),
        }

        if dry_run:
            record["status"] = "DRY_RUN_SUCCESS"
            record["message"] = "Simulated critical alert dispatch completed cleanly."
        elif not self.telegram_sender.is_configured():
            record["status"] = "SKIPPED_UNCONFIGURED"
            record["message"] = "Telegram credentials unset; critical alert safely logged."
        else:
            try:
                success = self.telegram_sender.send_message(payload, parse_mode="HTML")
                if success:
                    record["status"] = "SENT_SUCCESS"
                    record["message"] = "Critical health notification delivered."
                else:
                    record["status"] = "SEND_FAILED"
                    record["message"] = "Telegram API responded with failure."
            except Exception as e:
                record["status"] = "OFFLINE_FAILED"
                record["message"] = f"Dispatch failed gracefully: {str(e)}"

        self.reports_dir.mkdir(parents=True, exist_ok=True)
        with open(self.dispatch_log_path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)

        return record


def main():
    parser = argparse.ArgumentParser(description="MIP Alert & Telegram Notification Dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Format and log alert without sending network call")
    parser.add_argument("--print-only", action="store_true", help="Print formatted message payload to stdout")

    args = parser.parse_args()
    dispatcher = AlertDispatcher(PROJECT_ROOT)

    if args.print_only:
        print(dispatcher.format_alert_payload())
        sys.exit(0)

    result = dispatcher.dispatch(dry_run=args.dry_run)
    print(f"Alert Dispatch Result: {result.get('status')} — {result.get('message')}")


if __name__ == "__main__":
    main()
