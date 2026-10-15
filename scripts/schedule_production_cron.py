#!/usr/bin/env python3
"""
MIP Android — Autonomous Production Cron Daemon & Scheduler CLI
Phase 42: Headless scheduler, cron generator, trading calendar evaluation, and bounded log rotation.

Provides:
1. CLI utility to print standard crontab entries for unattended EOD execution.
2. Headless daemon mode (--daemon) that monitors market close (18:30 IST) on trading days.
3. Rotating file logging to logs/production_pipeline.log (10 MB per file, max 5 backups).
"""

import os
import sys
import time
import argparse
import logging
from logging.handlers import RotatingFileHandler
import datetime
import json
from pathlib import Path
from typing import List, Optional, Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_production_pipeline import HeadlessProductionPipeline


def setup_scheduler_logging(
    log_dir: Optional[Path] = None,
    log_filename: str = "production_pipeline.log",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
    logger_name: str = "MIPScheduler",
) -> logging.Logger:
    """
    Initializes a RotatingFileHandler to prevent disk space exhaustion on mobile storage.
    Enforces maximum 10 MB per log file with up to 5 rotated backup archives.
    """
    target_dir = Path(log_dir) if log_dir else PROJECT_ROOT / "logs"
    target_dir.mkdir(parents=True, exist_ok=True)
    log_file = target_dir / log_filename

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    existing_paths = [
        getattr(h, "baseFilename", "")
        for h in logger.handlers
        if isinstance(h, RotatingFileHandler)
    ]
    if str(log_file.resolve()) not in existing_paths:
        handler = RotatingFileHandler(
            str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in logger.handlers):
            console = logging.StreamHandler(sys.stdout)
            console.setFormatter(formatter)
            logger.addHandler(console)

    return logger


class ProductionScheduler:
    """Institutional unattended cron and daemon scheduler for Project MIP."""

    IST_OFFSET = datetime.timedelta(hours=5, minutes=30)
    EOD_HOUR_IST = 18
    EOD_MINUTE_IST = 30

    def __init__(self, base_dir: Path = PROJECT_ROOT, logger: Optional[logging.Logger] = None):
        self.base_dir = Path(base_dir)
        self.calendar_path = self.base_dir / "data" / "trading_calendar.txt"
        self.logger = logger or setup_scheduler_logging(self.base_dir / "logs")
        self._cached_dates: Optional[List[str]] = None

    def get_trading_calendar_dates(self) -> List[str]:
        """Loads and caches sorted trading days from trading_calendar.txt."""
        if self._cached_dates is None:
            if not self.calendar_path.exists():
                raise FileNotFoundError(f"Trading calendar not found at {self.calendar_path}")
            with open(self.calendar_path, "r", encoding="utf-8") as f:
                dates = [line.strip() for line in f if line.strip()]
            self._cached_dates = sorted(dates)
        return self._cached_dates

    def is_trading_day(self, date_str: str) -> bool:
        """Determines if a specific date (YYYY-MM-DD) is an official NSE trading session."""
        dates = self.get_trading_calendar_dates()
        return date_str in dates

    def get_executed_sessions(self) -> List[str]:
        """Loads list of trading dates for which production pipeline has completed."""
        state_file = self.base_dir / "logs" / "scheduler_state.json"
        if not state_file.exists():
            return []
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("completed_sessions", [])
        except Exception:
            return []

    def mark_session_completed(self, date_str: str) -> None:
        """Atomically records completed session to prevent duplicate execution loops."""
        state_file = self.base_dir / "logs" / "scheduler_state.json"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        sessions = self.get_executed_sessions()
        if date_str not in sessions:
            sessions.append(date_str)
        try:
            tmp_file = state_file.parent / f"{state_file.name}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump({"completed_sessions": sessions, "last_updated": datetime.datetime.now(datetime.timezone.utc).isoformat()}, f, indent=2)
            tmp_file.replace(state_file)
        except Exception as e:
            self.logger.warning(f"Could not persist scheduler session state: {e}")

    def get_next_market_close(self, now_utc: Optional[datetime.datetime] = None) -> datetime.datetime:
        """
        Calculates the next upcoming 18:30 IST market close datetime (in UTC).
        If today is a trading day and current time < 18:30 IST, returns today's 18:30 IST in UTC.
        Otherwise, finds the next trading day in the calendar and returns its 18:30 IST in UTC.
        """
        now = now_utc or datetime.datetime.now(datetime.timezone.utc)
        now_ist = now + self.IST_OFFSET
        today_str = now_ist.strftime("%Y-%m-%d")

        dates = self.get_trading_calendar_dates()

        # Check if today is a trading day and 18:30 IST hasn't passed
        today_close_ist = datetime.datetime(
            year=now_ist.year,
            month=now_ist.month,
            day=now_ist.day,
            hour=self.EOD_HOUR_IST,
            minute=self.EOD_MINUTE_IST,
            second=0,
            tzinfo=datetime.timezone.utc,  # treat as naive offset for calculation
        )

        if self.is_trading_day(today_str) and now_ist.time() < datetime.time(self.EOD_HOUR_IST, self.EOD_MINUTE_IST):
            close_utc = today_close_ist - self.IST_OFFSET
            return close_utc

        # Otherwise, search subsequent trading days
        future_dates = [d for d in dates if d > today_str]
        if not future_dates:
            raise RuntimeError("Trading calendar does not contain future trading sessions.")

        next_date_str = future_dates[0]
        y, m, d = map(int, next_date_str.split("-"))
        next_close_ist = datetime.datetime(y, m, d, self.EOD_HOUR_IST, self.EOD_MINUTE_IST, 0, tzinfo=datetime.timezone.utc)
        return next_close_ist - self.IST_OFFSET

    def generate_crontab_entry(
        self,
        python_bin: Optional[str] = None,
        script_path: Optional[str] = None,
        cron_expr: str = "30 18 * * 1-5",
        mode: str = "pipeline",
    ) -> str:
        """Generates standard crontab configuration line for unattended daily EOD execution."""
        py_path = python_bin or sys.executable
        if mode == "daemon_step":
            runner_path = script_path or f"{self.base_dir / 'scripts' / 'schedule_production_cron.py'} --once"
            log_file = self.base_dir / "logs" / "scheduler_daemon.log"
            desc = "Calendar-Aware Daemon Step (--once)"
        else:
            runner_path = script_path or str(self.base_dir / "scripts" / "run_production_pipeline.py")
            log_file = self.base_dir / "logs" / "production_pipeline.log"
            desc = "Direct Production Pipeline"

        entry = (
            f"# Project MIP Unattended EOD Production Momentum Scanner ({desc}: 18:30 IST Weekdays)\n"
            f"{cron_expr} cd {self.base_dir} && {py_path} {runner_path} >> {log_file} 2>&1\n"
        )
        return entry

    def run_daemon_step(
        self,
        universe: str = "NIFTY750",
        dry_run: bool = False,
        now_utc: Optional[datetime.datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates current session against trading calendar and executes pipeline if due.
        Point-in-time safe, idempotent, and non-blocking.
        """
        now_utc = now_utc or datetime.datetime.now(datetime.timezone.utc)
        now_ist = now_utc + self.IST_OFFSET
        today_str = now_ist.strftime("%Y-%m-%d")

        is_trading = self.is_trading_day(today_str)
        market_closed_today = now_ist.time() >= datetime.time(self.EOD_HOUR_IST, self.EOD_MINUTE_IST)

        status_info = {
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_ist": now_ist.isoformat(),
            "today": today_str,
            "is_trading_day": is_trading,
            "market_closed_today": market_closed_today,
            "action_taken": "IDLE",
        }

        if not is_trading:
            self.logger.info(f"Scheduler: {today_str} is not a trading session. Standing by.")
            status_info["reason"] = "NON_TRADING_DAY"
            return status_info

        if not market_closed_today:
            self.logger.info(f"Scheduler: Market is still active today ({now_ist.strftime('%H:%M')} < 18:30 IST). Standing by.")
            status_info["reason"] = "MARKET_HOURS_ACTIVE"
            return status_info

        if today_str in self.get_executed_sessions():
            self.logger.info(f"Scheduler: Production pipeline already completed for {today_str}. Standing by.")
            status_info["reason"] = "SESSION_ALREADY_COMPLETED"
            return status_info

        # Market is closed on a trading day
        self.logger.info(f"Scheduler: Market closed on trading day {today_str}. Initiating production pipeline dispatch.")
        if dry_run:
            self.logger.info("Scheduler: [DRY_RUN] Pipeline dispatch simulated successfully.")
            status_info["action_taken"] = "SIMULATED_DISPATCH"
            return status_info

        # Execute headless production pipeline
        pipeline = HeadlessProductionPipeline(base_dir=self.base_dir)
        telemetry = pipeline.run_pipeline(
            universe=universe,
            as_of_date=today_str,
            force_refresh=False,
            allow_stale=True,
            skip_health_check=False,
        )
        if telemetry.get("pipeline_status") == "SUCCESS":
            self.mark_session_completed(today_str)
        status_info["action_taken"] = "PIPELINE_EXECUTED"
        status_info["telemetry"] = telemetry
        self.logger.info(f"Scheduler: Pipeline completed with status {telemetry.get('pipeline_status')}")
        return status_info

    def run_daemon(
        self,
        poll_interval: int = 60,
        universe: str = "NIFTY750",
        dry_run: bool = False,
        max_iterations: Optional[int] = None,
    ) -> None:
        """Long-running polling daemon for headless environments without system cron."""
        self.logger.info(f"Starting MIP Production Scheduler Daemon (Poll Interval: {poll_interval}s, Universe: {universe})")
        iterations = 0

        try:
            while True:
                iterations += 1
                try:
                    self.run_daemon_step(universe=universe, dry_run=dry_run)
                except Exception as e:
                    self.logger.error(f"Scheduler Daemon step error: {e}", exc_info=True)

                if max_iterations is not None and iterations >= max_iterations:
                    self.logger.info(f"Daemon reached max iterations ({max_iterations}). Terminating.")
                    break

                time.sleep(poll_interval)
        except KeyboardInterrupt:
            self.logger.info("Scheduler Daemon stopped by user.")


def main():
    parser = argparse.ArgumentParser(description="MIP Production Cron Scheduler & Daemon")
    parser.add_argument("--print-crontab", action="store_true", help="Print standard crontab entry")
    parser.add_argument("--mode", type=str, choices=["pipeline", "daemon_step"], default="daemon_step", help="Crontab target mode (pipeline or daemon_step)")
    parser.add_argument("--daemon", action="store_true", help="Run as long-running polling daemon")
    parser.add_argument("--poll-interval", type=int, default=60, help="Daemon poll interval in seconds")
    parser.add_argument("--universe", type=str, default="NIFTY750", help="Target universe mode")
    parser.add_argument("--dry-run", action="store_true", help="Simulate execution without running scan")
    parser.add_argument("--once", action="store_true", help="Run a single daemon evaluation step and exit")

    args = parser.parse_args()
    scheduler = ProductionScheduler(PROJECT_ROOT)

    if args.print_crontab:
        sys.stdout.write(scheduler.generate_crontab_entry(mode=args.mode))
        sys.exit(0)

    if args.once:
        res = scheduler.run_daemon_step(universe=args.universe, dry_run=args.dry_run)
        print(f"Daemon step completed: {res.get('action_taken')} ({res.get('reason', 'OK')})")
        sys.exit(0)

    if args.daemon:
        scheduler.run_daemon(
            poll_interval=args.poll_interval,
            universe=args.universe,
            dry_run=args.dry_run,
        )
        sys.exit(0)

    # Default: print crontab entry and next market close
    print("MIP Production Scheduler CLI")
    print("----------------------------")
    next_close = scheduler.get_next_market_close()
    print(f"Next Market Close (UTC): {next_close.isoformat()}")
    next_close_ist = next_close + scheduler.IST_OFFSET
    print(f"Next Market Close (IST): {next_close_ist.strftime('%Y-%m-%d %H:%M:%S IST')}")
    print("\nCrontab Configuration:")
    print(scheduler.generate_crontab_entry())


if __name__ == "__main__":
    main()
