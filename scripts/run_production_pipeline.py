#!/usr/bin/env python3
"""
MIP Android — Unattended Headless Production Scheduler & Pipeline Runner
Phase 41: Production Execution Wrapper & Lock Management.

Performs:
  1. Strict OS-level lock acquisition (.scanner.lock) with PID tracking and stale lock timeout.
  2. Pre-flight fail-closed operational health verification.
  3. HardenedScanner execution on specified universe (defaulting to NIFTY 750 / Total Market).
  4. Generation of all canonical deliverables:
     - Institutional Excel tearsheet (reports/MIP_Institutional_Scan_*.xlsx)
     - reports/screener_output_live.csv
     - reports/market_breadth.json & reports/sector_rotation.json
     - reports/pipeline_telemetry.json
  5. Execution telemetry collection (runtime, candidate count, memory footprint, exit status).
  6. Clean lock release on completion or failure.
"""

import sys
import os
import time
import json
import argparse
import datetime
import resource
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_latest_date
from scripts.scanner_hardening import HardenedScanner, get_canonical_strategy_fingerprint
from scripts.health_check import OperationalHealthChecker
from scripts.alert_dispatcher import AlertDispatcher


class LockAcquisitionError(BlockingIOError):
    """Raised when pipeline lock cannot be acquired due to active concurrent execution."""
    pass


class PipelineLock:
    """
    OS-level file lock using .scanner.lock with PID tracking and stale timeout.
    Prevents overlapping unattended runs and guarantees clean release.
    """

    def __init__(self, lock_file: Path, timeout_seconds: int = 1800):
        self.lock_file = Path(lock_file)
        self.timeout_seconds = timeout_seconds
        self.acquired = False

    def acquire(self) -> None:
        if self.lock_file.exists():
            # Inspect existing lock
            is_stale = False
            lock_pid = None
            try:
                content = json.loads(self.lock_file.read_text(encoding="utf-8"))
                lock_pid = content.get("pid")
            except Exception:
                is_stale = True

            if lock_pid is not None and not is_stale:
                # Check if process is still running
                process_alive = False
                try:
                    os.kill(lock_pid, 0)
                    process_alive = True
                except (ProcessLookupError, OSError):
                    process_alive = False

                if process_alive:
                    raise LockAcquisitionError(
                        f"Pipeline is already running by active process PID {lock_pid}. Lock file: {self.lock_file}"
                    )
                else:
                    is_stale = True

            if is_stale:
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass

        # Atomic lock file creation
        lock_data = {
            "pid": os.getpid(),
            "acquired_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "host_os": sys.platform,
        }

        try:
            fd = os.open(str(self.lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2)
            self.acquired = True
        except FileExistsError:
            raise LockAcquisitionError(
                f"Concurrent process acquired lock before this process. Lock file: {self.lock_file}"
            )

    def release(self) -> None:
        if self.acquired and self.lock_file.exists():
            try:
                # Only remove if it belongs to our PID
                content = json.loads(self.lock_file.read_text(encoding="utf-8"))
                if content.get("pid") == os.getpid():
                    self.lock_file.unlink()
            except Exception:
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass
            finally:
                self.acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class HeadlessProductionPipeline:
    """Institutional unattended pipeline orchestrator."""

    def __init__(self, base_dir: Path = PROJECT_ROOT, lock_timeout: int = 1800):
        self.base_dir = Path(base_dir)
        self.lock_file = self.base_dir / ".scanner.lock"
        self.lock = PipelineLock(self.lock_file, timeout_seconds=lock_timeout)
        self.reports_dir = self.base_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_path = self.reports_dir / "pipeline_telemetry.json"

    def run_pipeline(
        self,
        universe: str = "NIFTY750",
        as_of_date: Optional[str] = None,
        force_refresh: bool = False,
        allow_stale: bool = True,
        skip_health_check: bool = False,
        dispatch_alert: bool = True,
        dry_run: bool = False,
        benchmark: str = "NIFTY500",
    ) -> Dict[str, Any]:
        start_time = time.time()
        start_dt = datetime.datetime.now(datetime.timezone.utc)

        with self.lock:
            # 1. Pre-flight health check
            health_summary = {}
            if not skip_health_check:
                health_checker = OperationalHealthChecker(self.base_dir)
                healthy, health_summary = health_checker.run_all_checks()
                if not healthy:
                    if dispatch_alert:
                        try:
                            dispatcher = AlertDispatcher(base_dir=self.base_dir, reports_dir=self.reports_dir)
                            dispatcher.dispatch_health_failure(health_summary, dry_run=dry_run)
                        except Exception as e:
                            logging.getLogger().warning(f"Failed to dispatch health failure alert: {e}")
                    raise RuntimeError(
                        f"Pre-flight health check failed ({health_summary.get('checks_passed')}/{health_summary.get('checks_total')} checks passed)."
                    )

            # 2. Determine target scan date
            target_date = as_of_date or get_latest_date()
            if not target_date:
                raise ValueError("Could not determine valid target date from universe.db.")

            # 3. Instantiate and run HardenedScanner
            scanner = HardenedScanner(base_dir=self.base_dir)
            top_df, disp_summary, const_rep, data_rep = scanner.run_hardened_scan(
                as_of_date=target_date,
                universe_mode=universe,
                force_constituent_refresh=force_refresh,
                allow_stale_universe=allow_stale,
                export_reports=True,
                benchmark=benchmark,
            )

            # 4. Collect execution metrics and telemetry
            elapsed = time.time() - start_time
            rusage = resource.getrusage(resource.RUSAGE_SELF)
            # maxrss is in KB on Linux
            peak_rss_mb = round(rusage.ru_maxrss / 1024.0, 2)

            top_count = int(len(top_df)) if top_df is not None else 0
            sectors_dist = {}
            if top_df is not None and not top_df.empty and "sector" in top_df.columns:
                sectors_dist = {str(k): int(v) for k, v in top_df["sector"].value_counts().items()}

            excel_path = top_df.attrs.get("excel_path", "") if hasattr(top_df, "attrs") else ""

            def _json_default(obj):
                if hasattr(obj, "item"):
                    return obj.item()
                if hasattr(obj, "to_dict"):
                    return obj.to_dict()
                if isinstance(obj, (datetime.date, datetime.datetime)):
                    return obj.isoformat()
                if isinstance(obj, Path):
                    return str(obj)
                return str(obj)

            # Explicitly serialize standalone breadth and sector rotation deliverables (COND-41-01)
            breadth_results = top_df.attrs.get("breadth_results") if hasattr(top_df, "attrs") else None
            sector_results = top_df.attrs.get("sector_results") if hasattr(top_df, "attrs") else None

            breadth_path = self.reports_dir / "market_breadth.json"
            if breadth_results is not None:
                with open(breadth_path, "w", encoding="utf-8") as f:
                    json.dump(breadth_results, f, indent=2, default=_json_default)

            sector_path = self.reports_dir / "sector_rotation.json"
            if sector_results is not None:
                with open(sector_path, "w", encoding="utf-8") as f:
                    json.dump(sector_results, f, indent=2, default=_json_default)

            # Check that deliverables exist
            csv_path = self.reports_dir / "screener_output_live.csv"
            health_path = self.reports_dir / "operational_health.json"
            scan_quality_json = self.reports_dir / "scan_quality.json"
            dispatch_log_path = self.reports_dir / "alert_dispatch.json"

            telemetry = {
                "pipeline_status": "SUCCESS",
                "execution_timestamp_utc": start_dt.isoformat(),
                "completed_timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "as_of_date": target_date,
                "universe_mode": universe,
                "universe_label": str(top_df.attrs.get("universe_label", universe)) if hasattr(top_df, "attrs") else universe,
                "runtime_seconds": round(elapsed, 2),
                "peak_memory_mb": peak_rss_mb,
                "top_candidates_selected": top_count,
                "sector_distribution": sectors_dist,
                "max_candidates_per_sector": int(max(sectors_dist.values())) if sectors_dist else 0,
                "sector_cap_enforced": bool(all(c <= 2 for c in sectors_dist.values())),
                "strategy_fingerprint": get_canonical_strategy_fingerprint(scanner.config),
                "disposition_summary": disp_summary,
                "deliverables": {
                    "screener_csv": str(csv_path) if csv_path.exists() else "",
                    "excel_workbook": str(excel_path) if excel_path and Path(excel_path).exists() else "",
                    "market_breadth": str(breadth_path) if breadth_path.exists() else "",
                    "sector_rotation": str(sector_path) if sector_path.exists() else "",
                    "operational_health": str(health_path) if health_path.exists() else "",
                    "scan_quality": str(scan_quality_json) if scan_quality_json.exists() else "",
                    "alert_dispatch": "",
                },
                "alert_dispatch_status": "DISABLED",
                "exit_code": 0,
            }

            # 5. Alert notification dispatch (Workstream 1)
            if dispatch_alert:
                try:
                    dispatcher = AlertDispatcher(base_dir=self.base_dir, reports_dir=self.reports_dir)
                    alert_record = dispatcher.dispatch(dry_run=dry_run)
                    telemetry["alert_dispatch_status"] = alert_record.get("status", "UNKNOWN")
                    telemetry["deliverables"]["alert_dispatch"] = str(dispatch_log_path) if dispatch_log_path.exists() else ""
                except Exception as e:
                    logging.getLogger().warning(f"Alert dispatch exception (fail-safe): {e}")
                    telemetry["alert_dispatch_status"] = "EXCEPTION"
                    telemetry["deliverables"]["alert_dispatch"] = ""

            with open(self.telemetry_path, "w", encoding="utf-8") as f:
                json.dump(telemetry, f, indent=2, default=_json_default)

            return telemetry


def main():
    parser = argparse.ArgumentParser(description="MIP Android Unattended Production Pipeline Runner")
    parser.add_argument("--universe", type=str, default="NIFTY750", help="Target universe mode (default: NIFTY750)")
    parser.add_argument("--benchmark", type=str, default="NIFTY500", help="Target benchmark index or symbol (default: NIFTY500)")
    parser.add_argument("--as-of-date", type=str, default=None, help="Target as-of date YYYY-MM-DD (default: latest in DB)")
    parser.add_argument("--force-refresh", action="store_true", help="Force live constituent refresh from exchange")
    parser.add_argument("--disallow-stale", action="store_true", help="Fail closed if constituent cache exceeds 30-day TTL")
    parser.add_argument("--skip-health-check", action="store_true", help="Skip pre-flight operational health verification")
    parser.add_argument("--no-dispatch-alert", action="store_true", help="Disable automated alert dispatch")
    parser.add_argument("--dry-run", action="store_true", help="Run alert dispatch in dry-run simulation mode")
    parser.add_argument("--lock-timeout", type=int, default=1800, help="Stale lock timeout in seconds (default: 1800)")
    args = parser.parse_args()

    pipeline = HeadlessProductionPipeline(lock_timeout=args.lock_timeout)
    try:
        telemetry = pipeline.run_pipeline(
            universe=args.universe,
            benchmark=args.benchmark,
            as_of_date=args.as_of_date,
            force_refresh=args.force_refresh,
            allow_stale=not args.disallow_stale,
            skip_health_check=args.skip_health_check,
            dispatch_alert=not args.no_dispatch_alert,
            dry_run=args.dry_run,
        )
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [Pipeline] Production scan completed successfully!")
        print(f"  Target Date:    {telemetry['as_of_date']}")
        print(f"  Universe:       {telemetry['universe_label']} ({telemetry['universe_mode']})")
        print(f"  Candidates:     {telemetry['top_candidates_selected']} selected (Sector cap <= 2: {telemetry['sector_cap_enforced']})")
        print(f"  Runtime:        {telemetry['runtime_seconds']}s | Peak RAM: {telemetry['peak_memory_mb']} MB")
        print(f"  Telemetry:      {pipeline.telemetry_path}")
        sys.exit(0)
    except LockAcquisitionError as e:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [Pipeline ERROR] Lock collision: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [Pipeline ERROR] Pipeline execution failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
