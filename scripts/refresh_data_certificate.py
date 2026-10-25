#!/usr/bin/env python3
"""Regenerate certificates/PRODUCTION_READINESS_CERTIFICATE.json from the live tree.

The certificate is the machine-readable contract that future runs use to
recognise the dataset. It records:

  * database bytes / rows / max date / sha256 / integrity check
  * PIT membership certificate (verdict, anchors, coverage, table hash)
  * strategy fingerprint (9 frozen parameters)
  * test evidence, if reports/test_evidence.json is present
  * data-quality limitations that are still open (price discontinuities, CA
    registry coverage, calendar horizon, unmapped members)

It deliberately does NOT claim blanket production readiness while the price
series still contains non-corporate-action discontinuities.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "universe.db"
PIT_CERT = ROOT / "certificates" / "PIT_UNIVERSE_CERTIFICATE.json"
OUT = ROOT / "certificates" / "PRODUCTION_READINESS_CERTIFICATE.json"
TESTS = ROOT / "reports" / "test_evidence.json"
VERIFIED = ROOT / "reports" / "verified"

sys.path.insert(0, str(ROOT))
from scripts.scanner_hardening import get_canonical_strategy_fingerprint  # noqa: E402
from core.config import MIPScannerConfig  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def db_stats() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        rows = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
        symbols = con.execute("SELECT COUNT(DISTINCT symbol) FROM prices").fetchone()[0]
        min_d, max_d = con.execute("SELECT MIN(date), MAX(date) FROM prices").fetchone()
        membership = con.execute("SELECT COUNT(*) FROM index_membership").fetchone()[0]
        manifest = dict(con.execute("SELECT key, value FROM pit_manifest").fetchall())
    finally:
        con.close()
    return {
        "path": str(DB.relative_to(ROOT)),
        "bytes": DB.stat().st_size,
        "sha256": sha256(DB),
        "row_count": int(rows),
        "symbol_count": int(symbols),
        "min_date": min_d,
        "max_date": max_d,
        "integrity_check": integrity,
        "index_membership_rows": int(membership),
        "pit_manifest": manifest,
    }


def price_repairs() -> dict:
    """Ledger summary for the 2026-10-25 vendor-artifact repair."""
    ledger = ROOT / "data" / "price_repairs.json"
    if not ledger.exists():
        return {"status": "not_run"}
    data = json.loads(ledger.read_text())
    return {
        "status": "APPLIED",
        "ledger": str(ledger.relative_to(ROOT)),
        "ledger_sha256": sha256(ledger),
        "spikes_flattened": data["counts"]["spikes"],
        "vendor_level_shifts": data["counts"]["shifts"],
        "vendor_batch_dates": data["counts"]["batch_dates"],
        "resume_gaps": data["counts"]["resumes"],
        "method": data["method"],
    }


def discontinuity_census() -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        df = pd.read_sql_query(
            "SELECT symbol, date, close FROM prices WHERE close > 0 ORDER BY symbol, date", con
        )
    finally:
        con.close()
    r = df.groupby("symbol")["close"].pct_change()
    ev = df[(r <= -0.35) | (r >= 0.5)]
    by_date = ev.groupby("date").size().sort_values(ascending=False)
    return {
        "events": int(len(ev)),
        "symbols": int(ev["symbol"].nunique()),
        "top_dates": {str(k): int(v) for k, v in by_date.head(8).items()},
        "status": "OPEN",
        "note": "Vendor-segment discontinuities not covered by the corporate-action registry; "
                "the live scanner fail-closes on them, the research backtester does not. "
                "Repair before citing any price-driven performance number.",
    }


def verified_campaign() -> dict:
    """Summarise the verified strategy campaign if present."""
    summary_p = VERIFIED / "campaign_summary.json"
    stats_p = VERIFIED / "statistics.json"
    top5_p = VERIFIED / "top5_final.csv"
    windows_p = VERIFIED / "window_robustness.csv"
    if not summary_p.exists():
        return {"status": "not_run"}
    summary = json.loads(summary_p.read_text())
    stats = json.loads(stats_p.read_text()) if stats_p.exists() else {}
    out = {
        "status": "COMPLETE",
        "universe": summary.get("universe"),
        "window": summary.get("window"),
        "engine": summary.get("engine"),
        "runs": summary.get("runs"),
        "grid_sharpe": {k: stats.get(k) for k in ("sharpe_mean", "sharpe_std", "sharpe_max")},
        "deflated_sharpe": {
            "best_config": stats.get("top", {}).get("sr_annual"),
            "expected_max_under_null": stats.get("top", {}).get("sr0_annual"),
            "dsr_best": stats.get("top", {}).get("dsr"),
        },
        "canonical": next((c for c in summary.get("config_matrix", [])
                           if str(c.get("config_name", "")).startswith("C_")), None),
    }
    if top5_p.exists():
        top5 = pd.read_csv(top5_p)
        top5 = top5[~top5["name"].astype(str).str.startswith("canonical")]
        out["top5"] = top5[["name", "py_cagr", "py_sharpe", "py_dd", "trades", "wins"]].to_dict("records")
    control_p = VERIFIED / "current_list_control.json"
    if control_p.exists():
        control = json.loads(control_p.read_text())
        out["current_list_control"] = control
        # The control runs on the Python engine, so compare with the Python
        # canonical run (not the C-kernel value in campaign_summary).
        py_p = VERIFIED / "python_validation.json"
        can_cagr = None
        if py_p.exists():
            for row in json.loads(py_p.read_text()):
                if str(row.get("name", "")).startswith("canonical"):
                    can_cagr = row.get("cagr_pct")
                    break
        if can_cagr is not None:
            out["python_canonical_cagr"] = round(float(can_cagr), 2)
            out["lookahead_overstatement_pp"] = round(float(control["cagr_pct"]) - float(can_cagr), 2)
    if windows_p.exists():
        w = pd.read_csv(windows_p)
        can = w[w["top_n"] == 20]
        if len(can):
            out["canonical_windows"] = {
                "windows": int(len(can)),
                "median_cagr": round(float(can["cagr"].median()), 2),
                "worst_cagr": round(float(can["cagr"].min()), 2),
                "median_excess": round(float(can["excess"].median()), 2),
                "beat_benchmark_pct": round(float((can["excess"] > 0).mean() * 100), 1),
            }
    return out


def main() -> int:
    stats = db_stats()
    pit = json.loads(PIT_CERT.read_text()) if PIT_CERT.exists() else {}
    tests = json.loads(TESTS.read_text()) if TESTS.exists() else {}

    cert = {
        "certificate_type": "DATA_INTEGRITY_AND_PIT_CERTIFICATE",
        "project_name": "Project MIP",
        "version": (ROOT / "VERSION").read_text().strip(),
        "issued_at_utc": datetime.now(timezone.utc).isoformat(),
        "governance_mode": "PIT_ANCHOR_VERIFIED__PRICE_DATA_PARTIAL",
        "verdict": "PIT_VERIFIED" if pit.get("verdict") == "PASS" else "PIT_UNVERIFIED",
        "strategy_fingerprint": get_canonical_strategy_fingerprint(MIPScannerConfig()),
        "database": stats,
        "pit_membership": {
            "certificate": str(PIT_CERT.relative_to(ROOT)),
            "certificate_sha256": sha256(PIT_CERT) if PIT_CERT.exists() else None,
            "verdict": pit.get("verdict"),
            "table_sha256": pit.get("table_sha256"),
            "snapshots": pit.get("snapshots"),
            "date_range": pit.get("date_range"),
            "anchors": pit.get("anchor_count"),
            "coverage_ratio": pit.get("coverage_ratio"),
            "mean_cross_source_jaccard": pit.get("mean_cross_source_jaccard"),
            "stored_in_database": "index_membership",
        },
        "verified_campaign": verified_campaign(),
        "verification_metrics": {
            "test_suite": tests or "not recorded for this run",
            "pit_gates": {g["check"]: g["passed"] for g in pit.get("gates", [])},
        },
        "data_quality": {
            "price_repairs": price_repairs(),
            "price_discontinuities": discontinuity_census(),
            "corporate_actions_registered": 6,
            "calendar_horizon": "data/trading_calendar.txt ends 2026-10-16; DB extends to 2026-10-19",
            "unmapped_pit_members": "8.1% of member-dates have no price series in universe.db",
        },
        "known_limitations": [
            "Remaining price breaks are isolated unregistered corporate actions (splits/bonuses) and the 2026-09-01 resume block; both are quarantined from selection for 252 sessions.",
            "Corporate-action registry covers 6 events; CCAVENUE/HEG breaks are unexplained.",
            "PIT membership before 2018-10-04 is press-release derived (no NSE anchor).",
            "Optimised grid settings are in-sample selections (Deflated Sharpe 0.72); no live track record yet.",
        ],
        "rebuild_commands": [
            "python3 scripts/build_pit_membership.py",
            "python3 scripts/verify_pit_membership.py --strict",
            "MIP_ALLOW_PROD_MUTATION=1 python3 scripts/load_pit_into_db.py --write",
            "python3 scripts/refresh_data_certificate.py",
            "python3 scripts/run_verified_campaign.py",
        ],
    }
    OUT.write_text(json.dumps(cert, indent=2), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"verdict={cert['verdict']} db_sha={stats['sha256'][:16]}… rows={stats['row_count']:,}")
    print(f"discontinuities={cert['data_quality']['price_discontinuities']['events']} (OPEN)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
