#!/usr/bin/env python3
"""
MIP Android — Operational Production Readiness Smoke & Verification Script
Phase 44: Pre-flight operational readiness verification, crontab path validation,
directory permission audits, and production certification assertion.
"""

import os
import sys
import json
import hashlib
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, Any

# Ensure project root in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.health_check import OperationalHealthChecker
from scripts.schedule_production_cron import ProductionScheduler
from scripts.scanner_hardening import get_canonical_strategy_fingerprint


def verify_production_readiness(base_dir: Path = PROJECT_ROOT) -> Dict[str, Any]:
    """Runs end-to-end diagnostics and asserts production deployment readiness."""
    base_dir = Path(base_dir)
    reports_dir = base_dir / "reports"
    logs_dir = base_dir / "logs"
    data_dir = base_dir / "data"
    reports_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    results = {
        "production_ready": False,
        "checks": {},
        "errors": [],
    }

    # 1. Operational Health Checks
    try:
        checker = OperationalHealthChecker(base_dir=base_dir)
        healthy, health_summary = checker.run_all_checks()
        results["checks"]["operational_health"] = {
            "passed": healthy,
            "overall_health": health_summary.get("overall_health"),
            "checks_passed": health_summary.get("checks_passed"),
            "checks_total": health_summary.get("checks_total"),
        }
        if not healthy:
            results["errors"].append(f"Operational health checks degraded: {health_summary.get('failed_checks')}")
    except Exception as e:
        results["checks"]["operational_health"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Operational health execution failed: {e}")

    # 2. Database Integrity Check
    try:
        db_path = data_dir / "universe.db"
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found at {db_path}")
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("PRAGMA quick_check")
        qc = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM prices")
        row_count = cursor.fetchone()[0]
        cursor.execute("SELECT MAX(date) FROM prices")
        max_date = cursor.fetchone()[0]
        conn.close()

        # Expected invariants come from the certificate, never from literals: a
        # data refresh must regenerate the certificate, and this check then
        # recognizes the new state automatically.
        cert_path = base_dir / "certificates" / "PRODUCTION_READINESS_CERTIFICATE.json"
        cert = json.loads(cert_path.read_text()) if cert_path.exists() else {}
        db_expect = cert.get("database") or cert.get("cryptographic_provenance", {}).get("database", {})
        db_sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
        db_ok = bool(
            qc == "ok"
            and db_expect
            and row_count == int(db_expect.get("row_count", -1))
            and max_date == db_expect.get("max_date")
            and db_sha == db_expect.get("sha256")
        )
        results["checks"]["database_integrity"] = {
            "passed": db_ok,
            "quick_check": qc,
            "row_count": row_count,
            "max_date": max_date,
            "sha256": db_sha,
            "expected": db_expect or "missing certificate",
        }
        if not db_ok:
            results["errors"].append(
                f"Database invariants mismatch vs certificate: qc={qc}, rows={row_count}, "
                f"max_date={max_date}, sha={db_sha[:16]}... — run scripts/refresh_data_certificate.py"
            )
    except Exception as e:
        results["checks"]["database_integrity"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Database inspection failed: {e}")

    # 3. Directory Write Permissions
    try:
        test_rep = reports_dir / ".perm_check"
        test_rep.write_text("ok", encoding="utf-8")
        test_rep.unlink()

        test_log = logs_dir / ".perm_check"
        test_log.write_text("ok", encoding="utf-8")
        test_log.unlink()

        results["checks"]["directory_permissions"] = {"passed": True}
    except Exception as e:
        results["checks"]["directory_permissions"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Directory permissions failed: {e}")

    # 4. Crontab Path Resolution
    try:
        scheduler = ProductionScheduler(base_dir=base_dir)
        crontab_entry_daemon = scheduler.generate_crontab_entry(mode="daemon_step")
        crontab_entry_pipeline = scheduler.generate_crontab_entry(mode="pipeline")

        daemon_script = base_dir / "scripts" / "schedule_production_cron.py"
        pipeline_script = base_dir / "scripts" / "run_production_pipeline.py"
        scripts_exist = daemon_script.exists() and pipeline_script.exists()

        results["checks"]["crontab_paths"] = {
            "passed": scripts_exist,
            "daemon_script_exists": daemon_script.exists(),
            "pipeline_script_exists": pipeline_script.exists(),
        }
        if not scripts_exist:
            results["errors"].append("One or more crontab target scripts are missing.")
    except Exception as e:
        results["checks"]["crontab_paths"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Crontab path validation failed: {e}")

    # 5. Canonical Strategy Fingerprint
    try:
        from core.config import MIPScannerConfig
        cfg = MIPScannerConfig()
        fp = get_canonical_strategy_fingerprint(cfg)
        canonical_fp = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"
        fp_ok = (fp == canonical_fp)
        results["checks"]["strategy_fingerprint"] = {
            "passed": fp_ok,
            "observed_fingerprint": fp,
            "canonical_fingerprint": canonical_fp,
        }
        if not fp_ok:
            results["errors"].append(f"Strategy fingerprint mismatch: {fp} != {canonical_fp}")
    except Exception as e:
        results["checks"]["strategy_fingerprint"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Strategy fingerprint validation failed: {e}")

    # 6. Core Modules Decoupling (27 modules)
    try:
        core_files = sorted([f.name for f in (base_dir / "core").glob("*.py")])
        core_ok = (len(core_files) == 27)
        results["checks"]["core_modules"] = {
            "passed": core_ok,
            "count": len(core_files),
        }
        if not core_ok:
            results["errors"].append(f"Core module count mismatch: {len(core_files)} != 27")
    except Exception as e:
        results["checks"]["core_modules"] = {"passed": False, "error": str(e)}
        results["errors"].append(f"Core module audit failed: {e}")

    # Overall determination
    all_passed = all(c.get("passed", False) for c in results["checks"].values())
    results["production_ready"] = all_passed

    # Save readiness report
    readiness_path = reports_dir / "production_readiness.json"
    with open(readiness_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    return results


def main():
    parser = argparse.ArgumentParser(description="MIP Production Readiness Smoke & Verification")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    results = verify_production_readiness()

    if args.json:
        print(json.dumps(results, indent=2))
        sys.exit(0 if results["production_ready"] else 1)

    print("=" * 70)
    print("           PROJECT MIP — PRODUCTION READINESS VERIFICATION")
    print("=" * 70)
    for name, c in results["checks"].items():
        status = "[PASS]" if c.get("passed") else "[FAIL]"
        print(f"  {status} {name.replace('_', ' ').title()}: passed={c.get('passed')}")

    print("-" * 70)
    if results["production_ready"]:
        print("STATUS: PRODUCTION_READY: TRUE")
        print("=" * 70)
        sys.exit(0)
    else:
        print("STATUS: PRODUCTION_READY: FALSE")
        for err in results["errors"]:
            print(f"  ERROR: {err}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
