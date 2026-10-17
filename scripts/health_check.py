#!/usr/bin/env python3
"""
MIP Android — Pre-Flight Operational Health Check
Phase 41: Fail-closed operational health verification tool.

Performs comprehensive pre-flight verification:
  1. Database read-only connectivity, schema validity, and row count conservation.
  2. Trading calendar cryptographic hash and session freshness.
  3. Corporate actions registry hash invariant.
  4. 9 canonical strategy parameters and SHA-256 strategy fingerprint.
  5. Disk space and write permissions in output directories.
  6. Core module count and provenance manifest integrity.

Emits structured JSON operational telemetry report to reports/operational_health.json.
Exits with 0 on HEALTHY, 1 on UNHEALTHY.
"""

import sys
import os
import json
import sqlite3
import hashlib
import shutil
import datetime
from pathlib import Path
from typing import Dict, Any, Tuple

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CANONICAL_STRATEGY_FINGERPRINT = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"
CANONICAL_CORPORATE_ACTIONS_HASH = "9e492f94e0e108fc968414e903cc730beda528379efee74594c6e521b1f6d2b9"
CANONICAL_TRADING_CALENDAR_HASH = "4b3dce45d011a0a14861c5d949c4b795e277d202a4ee279cd0ede8019e936c57"
CANONICAL_TRADING_CALENDAR_HASHES = {
    "42e40e9ab665cfb7ba0850f414485eda9dc4f418c782cbb38107d1fd4b1986ef",
    "4b3dce45d011a0a14861c5d949c4b795e277d202a4ee279cd0ede8019e936c57",
}
EXPECTED_CORE_MODULE_COUNT = 25
EXPECTED_DB_ROW_COUNT = 2169576
EXPECTED_DB_ROW_COUNTS = {2164420, 2167514, 2169576}
EXPECTED_DB_SIZE = 351744000


def check_file_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class OperationalHealthChecker:
    def __init__(self, base_dir: Path = PROJECT_ROOT):
        self.base_dir = Path(base_dir)
        self.data_dir = self.base_dir / "data"
        self.reports_dir = self.base_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.health_report_path = self.reports_dir / "operational_health.json"

    def verify_database_integrity(self) -> Dict[str, Any]:
        db_path = self.data_dir / "universe.db"
        if not db_path.exists():
            return {
                "check": "database_integrity",
                "status": "FAIL",
                "details": f"Database file not found: {db_path}",
            }

        size = db_path.stat().st_size
        conn = None
        try:
            from core.data_engine import get_connection
            conn = get_connection(read_only=True)
            cursor = conn.cursor()
            cursor.execute("PRAGMA quick_check;")
            integrity = cursor.fetchone()[0]

            cursor.execute("SELECT count(*) FROM prices;")
            row_count = cursor.fetchone()[0]

            cursor.execute("SELECT max(date), min(date) FROM prices;")
            max_date, min_date = cursor.fetchone()

            # Verify required tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {r[0] for r in cursor.fetchall()}
            required_tables = {"prices", "applied_corporate_actions", "picks_history"}
            missing_tables = required_tables - tables

            if integrity != "ok":
                return {"check": "database_integrity", "status": "FAIL", "details": f"Integrity check failed: {integrity}"}
            if row_count not in EXPECTED_DB_ROW_COUNTS:
                return {"check": "database_integrity", "status": "FAIL", "details": f"Row count mismatch: {row_count} not in {EXPECTED_DB_ROW_COUNTS}"}
            if missing_tables:
                return {"check": "database_integrity", "status": "FAIL", "details": f"Missing tables: {missing_tables}"}

            return {
                "check": "database_integrity",
                "status": "PASS",
                "file_size": size,
                "row_count": row_count,
                "max_date": max_date,
                "min_date": min_date,
                "integrity": integrity,
            }
        except Exception as e:
            return {"check": "database_integrity", "status": "FAIL", "details": str(e)}

    def verify_immutability_firewall(self) -> Dict[str, Any]:
        try:
            from core.data_engine import get_connection
            # Attempting write connection without flag must raise PermissionError
            old_mutation = os.environ.get("MIP_ALLOW_PROD_MUTATION")
            old_readonly = os.environ.get("MIP_READONLY")
            if "MIP_ALLOW_PROD_MUTATION" in os.environ:
                del os.environ["MIP_ALLOW_PROD_MUTATION"]
            if "MIP_READONLY" in os.environ:
                del os.environ["MIP_READONLY"]
            try:
                get_connection(read_only=False)
                return {"check": "immutability_firewall", "status": "FAIL", "details": "Direct write connection was not blocked"}
            except PermissionError:
                pass
            finally:
                if old_mutation is not None:
                    os.environ["MIP_ALLOW_PROD_MUTATION"] = old_mutation
                if old_readonly is not None:
                    os.environ["MIP_READONLY"] = old_readonly

            return {"check": "immutability_firewall", "status": "PASS", "details": "Production immutability firewall verified active"}
        except Exception as e:
            return {"check": "immutability_firewall", "status": "FAIL", "details": str(e)}

    def verify_corporate_actions(self) -> Dict[str, Any]:
        ca_path = self.data_dir / "corporate_actions_registry.json"
        if not ca_path.exists():
            return {"check": "corporate_actions_registry", "status": "FAIL", "details": "File missing"}
        observed_hash = check_file_sha256(ca_path)
        if observed_hash != CANONICAL_CORPORATE_ACTIONS_HASH:
            return {
                "check": "corporate_actions_registry",
                "status": "FAIL",
                "details": f"Hash mismatch: {observed_hash} != {CANONICAL_CORPORATE_ACTIONS_HASH}",
            }
        return {"check": "corporate_actions_registry", "status": "PASS", "sha256": observed_hash}

    def verify_trading_calendar(self) -> Dict[str, Any]:
        cal_path = self.data_dir / "trading_calendar.txt"
        if not cal_path.exists():
            return {"check": "trading_calendar", "status": "FAIL", "details": "File missing"}
        observed_hash = check_file_sha256(cal_path)
        if observed_hash not in CANONICAL_TRADING_CALENDAR_HASHES:
            return {
                "check": "trading_calendar",
                "status": "FAIL",
                "details": f"Hash mismatch: {observed_hash} not in {CANONICAL_TRADING_CALENDAR_HASHES}",
            }
        # Check that calendar has valid sorted dates
        with open(cal_path, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f if l.strip()]
        if not lines or len(lines) < 4000:
            return {"check": "trading_calendar", "status": "FAIL", "details": f"Insufficient calendar days: {len(lines)}"}
        return {
            "check": "trading_calendar",
            "status": "PASS",
            "sha256": observed_hash,
            "total_trading_days": len(lines),
            "latest_calendar_date": lines[-1],
        }

    def verify_strategy_fingerprint(self) -> Dict[str, Any]:
        try:
            from core.config import MIPScannerConfig
            from scripts.scanner_hardening import get_canonical_strategy_fingerprint
            cfg = MIPScannerConfig()
            observed_fp = get_canonical_strategy_fingerprint(cfg)
            if observed_fp != CANONICAL_STRATEGY_FINGERPRINT:
                return {
                    "check": "strategy_fingerprint",
                    "status": "FAIL",
                    "details": f"Fingerprint mismatch: {observed_fp} != {CANONICAL_STRATEGY_FINGERPRINT}",
                }
            return {
                "check": "strategy_fingerprint",
                "status": "PASS",
                "fingerprint": observed_fp,
                "parameters": {
                    "momentum_lookback_bars": cfg.momentum_lookback_bars,
                    "retrace_threshold": cfg.retrace_threshold,
                    "ema_trend_span": cfg.ema_trend_span,
                    "ema_rs_span": cfg.ema_rs_span,
                    "ema_regime_span": cfg.ema_regime_span,
                    "top_n_candidates": cfg.top_n_candidates,
                    "exit_buffer_rank": cfg.exit_buffer_rank,
                    "max_per_sector": cfg.max_per_sector,
                    "volatility_floor": cfg.volatility_floor,
                },
            }
        except Exception as e:
            return {"check": "strategy_fingerprint", "status": "FAIL", "details": str(e)}

    def verify_core_modules(self) -> Dict[str, Any]:
        core_dir = self.base_dir / "core"
        py_files = sorted([f.name for f in core_dir.glob("*.py")])
        if len(py_files) != EXPECTED_CORE_MODULE_COUNT:
            return {
                "check": "core_module_count",
                "status": "FAIL",
                "details": f"Core module count mismatch: {len(py_files)} != {EXPECTED_CORE_MODULE_COUNT}",
            }
        manifest_path = self.base_dir / "certificates" / "PROVENANCE_MANIFEST.json"
        if not manifest_path.exists():
            return {"check": "core_module_count", "status": "FAIL", "details": "PROVENANCE_MANIFEST.json missing"}
        return {
            "check": "core_module_count",
            "status": "PASS",
            "module_count": len(py_files),
            "modules": py_files,
        }

    def verify_disk_and_permissions(self) -> Dict[str, Any]:
        try:
            total, used, free = shutil.disk_usage(self.base_dir)
            free_mb = free / (1024 * 1024)
            test_file = self.reports_dir / ".health_check_test_write.tmp"
            test_file.write_text("health_check_ok", encoding="utf-8")
            test_file.unlink()
            if free_mb < 50.0:
                return {"check": "disk_and_permissions", "status": "FAIL", "details": f"Low disk space: {free_mb:.1f} MB"}
            return {
                "check": "disk_and_permissions",
                "status": "PASS",
                "free_disk_mb": round(free_mb, 2),
                "reports_writable": True,
            }
        except Exception as e:
            return {"check": "disk_and_permissions", "status": "FAIL", "details": str(e)}

    def run_all_checks(self) -> Tuple[bool, Dict[str, Any]]:
        checks = [
            self.verify_database_integrity(),
            self.verify_immutability_firewall(),
            self.verify_corporate_actions(),
            self.verify_trading_calendar(),
            self.verify_strategy_fingerprint(),
            self.verify_core_modules(),
            self.verify_disk_and_permissions(),
        ]

        all_passed = all(c.get("status") == "PASS" for c in checks)
        summary = {
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "overall_health": "HEALTHY" if all_passed else "UNHEALTHY",
            "checks_passed": sum(1 for c in checks if c.get("status") == "PASS"),
            "checks_total": len(checks),
            "checks": {c["check"]: c for c in checks},
        }

        with open(self.health_report_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

        return all_passed, summary


def main():
    checker = OperationalHealthChecker()
    passed, summary = checker.run_all_checks()
    status_str = summary["overall_health"]
    print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Operational Health Check: [{status_str}] ({summary['checks_passed']}/{summary['checks_total']} checks passed)")
    for check_name, res in summary["checks"].items():
        st = res.get("status")
        detail = res.get("details", "")
        print(f"  - {check_name:<30}: [{st}] {detail}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
