"""
scripts/eod_headless_runner.py
Institutional Headless End-Of-Day (EOD) Automation Runner.
Designed for 18:30 IST cron jobs, GitHub Actions, and Termux schedules.
Integrates unified UserProfile, pre-flight health check, auto-fetch, scanner, portfolio rebalancer,
Kite 1-click basket generation, and optional Telegram alerts.
"""

import os
import sys
import json
import time
import argparse
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_base_dir
from nextgen.profile import UserProfile, load_user_profile, get_default_profile
from scripts.health_check import OperationalHealthChecker


class EODHeadlessRunner:
    """Institutional coordinator for automated end-of-day momentum scanning & rebalancing."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        profile: Optional[UserProfile] = None,
        reports_dir: Optional[Path] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir is not None else get_base_dir()
        self.profile = profile if profile is not None else load_user_profile()
        self.reports_dir = Path(reports_dir) if reports_dir is not None else (self.base_dir / "reports")
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_path = self.reports_dir / "eod_telemetry.json"

    def run_preflight_health(self) -> Tuple[bool, Dict[str, Any]]:
        """Executes full operational health check against 5 Quantitative Pillars."""
        checker = OperationalHealthChecker(self.base_dir)
        is_healthy, summary = checker.run_all_checks()
        return is_healthy, summary

    def run_eod_pipeline(
        self,
        dry_run: bool = False,
        skip_health_check: bool = False,
        target_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes end-to-end automated EOD pipeline:
        1. Configuration validation
        2. Pre-flight health check
        3. Automated bhavcopy auto-fetch (if configured)
        4. Screener execution with Composite Alpha & Upper Circuit filters
        5. Portfolio rebalancing with deadband & tax-aware LTCG hurdle
        6. Zerodha Kite 1-Click basket generation
        7. Telemetry persistence & alert dispatch
        """
        start_time = time.time()
        start_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # 1. Profile Validation
        is_valid, validation_errors = self.profile.validate()
        if not is_valid:
            telemetry = {
                "status": "FAILED",
                "error": f"Invalid UserProfile configuration: {validation_errors}",
                "execution_timestamp": start_iso,
                "elapsed_seconds": round(time.time() - start_time, 2),
            }
            self._save_telemetry(telemetry)
            return telemetry

        # 2. Pre-flight health check
        health_summary = {}
        if not skip_health_check:
            is_healthy, health_summary = self.run_preflight_health()
            if not is_healthy:
                telemetry = {
                    "status": "HEALTH_CHECK_FAILED",
                    "health_summary": health_summary,
                    "execution_timestamp": start_iso,
                    "elapsed_seconds": round(time.time() - start_time, 2),
                }
                self._save_telemetry(telemetry)
                return telemetry

        # 3. Handle Dry Run Execution
        if dry_run:
            elapsed = time.time() - start_time
            telemetry = {
                "status": "SUCCESS",
                "dry_run": True,
                "execution_timestamp": start_iso,
                "completed_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "capital": self.profile.portfolio.capital,
                "universe": self.profile.portfolio.universe,
                "top_n": self.profile.portfolio.top_n,
                "deadband_inr": self.profile.execution_guards.deadband_inr,
                "elapsed_seconds": round(elapsed, 2),
                "telemetry_file": str(self.telemetry_path),
            }
            self._save_telemetry(telemetry)
            return telemetry

        # 4. Live Pipeline Execution
        try:
            from scripts.run_production_pipeline import HeadlessProductionPipeline
            from core.portfolio import PortfolioManager

            # Run production scanner
            pipeline = HeadlessProductionPipeline(self.base_dir)
            prod_telemetry = pipeline.run_pipeline(
                universe=self.profile.portfolio.universe,
                as_of_date=target_date,
                allow_stale=True,
                skip_health_check=True,  # Already checked above
                dry_run=False,
                benchmark=self.profile.portfolio.benchmark,
            )

            # Generate Portfolio Rebalance Tickets
            pm = PortfolioManager(self.base_dir)
            orders = pm.generate_rebalance_orders(
                capital=self.profile.portfolio.capital,
                cash=self.profile.portfolio.cash,
                top_n=self.profile.portfolio.top_n,
                exit_buffer_rank=self.profile.portfolio.exit_buffer_rank,
                sizing_mode=self.profile.portfolio.sizing_model,
                max_per_sector=self.profile.execution_guards.max_sector_allocation,
                as_of_date=target_date,
                min_trade_amount_inr=self.profile.execution_guards.deadband_inr,
                min_weight_drift_pct=self.profile.execution_guards.deadband_pct,
                tax_aware_rebalance=self.profile.execution_guards.tax_aware_rebalance,
                enforce_delivery_exit_veto=self.profile.execution_guards.delivery_distribution_veto,
            )

            # Generate Kite basket
            basket_json_path = None
            basket_html_path = None
            if self.profile.automation.generate_kite_basket:
                basket_json_path, basket_html_path = pm.export_kite_basket(orders)

            elapsed = time.time() - start_time
            telemetry = {
                "status": "SUCCESS",
                "dry_run": False,
                "execution_timestamp": start_iso,
                "completed_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "capital": self.profile.portfolio.capital,
                "universe": self.profile.portfolio.universe,
                "top_n": self.profile.portfolio.top_n,
                "total_orders": len(orders),
                "buy_orders": int((orders["action"] == "BUY").sum()) if not orders.empty else 0,
                "sell_orders": int((orders["action"] == "SELL").sum()) if not orders.empty else 0,
                "kite_basket_json": str(basket_json_path) if basket_json_path else None,
                "kite_basket_html": str(basket_html_path) if basket_html_path else None,
                "elapsed_seconds": round(elapsed, 2),
                "telemetry_file": str(self.telemetry_path),
            }
            self._save_telemetry(telemetry)

            # Dispatch Telegram alert if enabled
            if self.profile.notifications.telegram_enabled and self.profile.notifications.telegram_bot_token:
                self._dispatch_telegram(telemetry)

            return telemetry

        except Exception as e:
            elapsed = time.time() - start_time
            telemetry = {
                "status": "EXECUTION_ERROR",
                "error": str(e),
                "execution_timestamp": start_iso,
                "elapsed_seconds": round(elapsed, 2),
                "telemetry_file": str(self.telemetry_path),
            }
            self._save_telemetry(telemetry)
            return telemetry

    def _save_telemetry(self, telemetry: Dict[str, Any]) -> None:
        """Atomically saves execution telemetry to reports/eod_telemetry.json."""
        tmp = self.telemetry_path.with_suffix(f".tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(telemetry, f, indent=2)
        os.replace(tmp, self.telemetry_path)

    def _dispatch_telegram(self, telemetry: Dict[str, Any]) -> None:
        """Dispatches summary alert to configured Telegram chat."""
        try:
            import urllib.request
            token = self.profile.notifications.telegram_bot_token
            chat_id = self.profile.notifications.telegram_chat_id
            text = (
                f"🚀 *Project MIP: EOD Rebalance Summary*\n"
                f"• Status: `{telemetry.get('status')}`\n"
                f"• Orders: {telemetry.get('total_orders', 0)} ({telemetry.get('buy_orders', 0)} BUY / {telemetry.get('sell_orders', 0)} SELL)\n"
                f"• Capital: ₹{telemetry.get('capital', 0):,.0f}\n"
                f"• Runtime: {telemetry.get('elapsed_seconds', 0)}s"
            )
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Institutional Headless EOD Runner")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without modifying live orders")
    parser.add_argument("--skip-health-check", action="store_true", help="Skip pre-flight operational health check")
    parser.add_argument("--date", type=str, default=None, help="Target as-of date (YYYY-MM-DD)")
    parser.add_argument("--universe", type=str, default=None, help="Universe override (e.g. NIFTY500, NIFTY100)")
    args = parser.parse_args()

    profile = load_user_profile()
    if args.universe:
        profile.portfolio.universe = args.universe

    runner = EODHeadlessRunner(profile=profile)
    telemetry = runner.run_eod_pipeline(
        dry_run=args.dry_run,
        skip_health_check=args.skip_health_check,
        target_date=args.date,
    )

    print(json.dumps(telemetry, indent=2))
    sys.exit(0 if telemetry.get("status") == "SUCCESS" else 1)


if __name__ == "__main__":
    main()
