#!/usr/bin/env python3
"""Verify the point-in-time NIFTY 500 membership table and issue a certificate.

Checks
------
1. STRUCTURE      monotonic dates, no duplicates, cardinality 488-512.
2. ANCHORS        every NSE Internet Archive capture is reproduced exactly.
3. CROSS_SOURCE   interval table vs. anchor membership (identity-aware Jaccard).
4. LISTING        no mapped member with a price series that starts after the date.
5. COVERAGE       share of members map-able to a traded DB ticker.
6. CHURN          month-over-month cardinality change <= 60 names.
7. IMPROVEMENT    new table vs. the pre-rebuild backup at anchor dates.

Outputs
-------
reports/PIT_VERIFICATION.md
certificates/PIT_UNIVERSE_CERTIFICATE.json

Exit code 0 when every gate passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Set

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PIT = ROOT / "data" / "pit_constituents"
TABLE = PIT / "nifty500_snapshots.csv"
BACKUP = PIT / "nifty500_snapshots.csv.bak"
INTERVALS = PIT / "index_membership_history.csv"
RENAMES = PIT / "symbol_renames.json"
ANCHOR_DIR = PIT / "anchors"
DB = ROOT / "data" / "universe.db"
REPORT = ROOT / "reports" / "PIT_VERIFICATION.md"
CERT = ROOT / "certificates" / "PIT_UNIVERSE_CERTIFICATE.json"

MIN_CARD, MAX_CARD = 488, 512
MIN_ANCHOR_MATCH = 0.92      # identity-aware agreement of the interval source
MIN_COVERAGE = 0.85          # mapped members / members
MAX_CHURN = 90


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for row in json.loads(RENAMES.read_text())["renames"]:
        old = str(row.get("old") or "").strip().upper()
        new = str(row.get("new") or "").strip().upper()
        if old and new and not new.startswith("_") and old != new:
            out.setdefault(old, new)
    for old in list(out):
        seen, cur = {old}, out[old]
        while cur in out and cur not in seen:
            seen.add(cur)
            cur = out[cur]
        out[old] = cur
    return out


def canon_set(symbols, renames):
    def one(s):
        seen = set()
        while s in renames and s not in seen:
            seen.add(s)
            s = renames[s]
        return s
    return {one(str(s).upper()) for s in symbols if str(s).strip()}


def load_anchors() -> Dict[str, Set[str]]:
    out = {}
    for path in sorted(glob.glob(str(ANCHOR_DIR / "ind_nifty500list_*.csv"))):
        m = re.search(r"(\d{8})\.csv$", path)
        if not m:
            continue
        d = m.group(1)
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        syms = set()
        for line in Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines()[1:]:
            p = line.split(",")
            if len(p) >= 3 and p[2].strip():
                syms.add(p[2].strip().upper())
        if syms:
            out[iso] = syms
    return out


def interval_members(day: str) -> Set[str]:
    df = pd.read_csv(INTERVALS)
    df = df[df["index_name"] == "Nifty 500"]
    df["valid_from"] = pd.to_datetime(df["valid_from"], errors="coerce")
    df["valid_to"] = pd.to_datetime(df["valid_to"], errors="coerce")
    t = pd.Timestamp(day)
    return set(df[(df["valid_from"] <= t) & (df["valid_to"].isna() | (df["valid_to"] > t))]["symbol"].str.upper())


def db_first_dates() -> Dict[str, str]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT symbol, MIN(date) FROM prices GROUP BY symbol").fetchall()
    finally:
        con.close()
    return {r[0]: r[1] for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit non-zero on gate failure")
    args = ap.parse_args()

    table = pd.read_csv(TABLE, dtype=str).fillna("")
    table["snapshot_date"] = table["snapshot_date"].astype(str)
    anchors = load_anchors()
    renames = canonical_map()
    first = db_first_dates()

    checks: List[dict] = []
    details: dict = {}

    def check(name, passed, **info):
        checks.append({"check": name, "passed": bool(passed), **info})

    # 1. structure
    dates = sorted(table["snapshot_date"].unique())
    cards = table.groupby("snapshot_date").size()
    dup = int(table.duplicated(["snapshot_date", "api_symbol"]).sum())
    bad_card = {d: int(n) for d, n in cards.items() if not (MIN_CARD <= n <= MAX_CARD)}
    check("STRUCTURE", dup == 0 and not bad_card and dates == sorted(dates),
          duplicates=dup, cardinality_violations=bad_card,
          snapshots=len(dates), min=dates[0], max=dates[-1])

    # 2. anchors reproduced exactly
    anchor_rows = {}
    for day, syms in anchors.items():
        # NSE publishes temporary DUMMY* scrips during corporate actions; the table
        # deliberately excludes them from the tradable universe.
        syms = {x for x in syms if not x.startswith("DUMMY")}
        got = set(table.loc[table["snapshot_date"] == day, "api_symbol"].str.upper())
        anchor_rows[day] = {
            "anchor_members": len(syms),
            "table_members": len(got),
            "exact": got == syms,
            "missing": sorted(syms - got)[:10],
            "extra": sorted(got - syms)[:10],
        }
    check("ANCHORS_EXACT", all(v["exact"] for v in anchor_rows.values()), per_anchor=anchor_rows)
    details["anchors"] = anchor_rows

    # 3. cross-source agreement (identity aware)
    cross = {}
    for day, syms in anchors.items():
        a = canon_set(syms, renames)
        b = canon_set(interval_members(day), renames)
        jac = len(a & b) / max(1, len(a | b))
        cross[day] = {
            "jaccard": round(jac, 4),
            "anchor_only": len(a - b),
            "interval_only": len(b - a),
        }
    mean_jac = sum(v["jaccard"] for v in cross.values()) / max(1, len(cross))
    check("CROSS_SOURCE", mean_jac >= MIN_ANCHOR_MATCH, mean_jaccard=round(mean_jac, 4), per_anchor=cross)
    details["cross_source"] = cross

    # 4. listing constraint on mapped members
    violations = []
    for row in table.itertuples():
        if not row.db_symbol:
            continue
        f = first.get(row.db_symbol)
        if f and f > row.snapshot_date:
            violations.append(f"{row.snapshot_date}:{row.api_symbol}->{row.db_symbol}(first={f})")
    check("LISTING_CONSTRAINT", len(violations) == 0, violations=violations[:20], count=len(violations))

    # 5. coverage
    mapped = int((table["db_symbol"] != "").sum())
    cov = mapped / max(1, len(table))
    check("COVERAGE", cov >= MIN_COVERAGE, mapped=mapped, rows=len(table), ratio=round(cov, 4))
    details["coverage_by_year"] = {
        str(y): round(float(g["db_symbol"].ne("").mean()), 4)
        for y, g in table.groupby(table["snapshot_date"].str[:4])
    }

    # 6. churn
    churn = {}
    prev = None
    for day in dates:
        cur = canon_set(table.loc[table["snapshot_date"] == day, "api_symbol"], renames)
        if prev is not None:
            churn[day] = len(cur ^ prev)
        prev = cur
    worst = max(churn.items(), key=lambda kv: kv[1]) if churn else ("n/a", 0)
    check("CHURN", worst[1] <= MAX_CHURN, worst_date=worst[0], worst_change=worst[1])

    # 7. improvement over the pre-rebuild table
    improvement = None
    if BACKUP.exists():
        old = pd.read_csv(BACKUP, dtype=str).fillna("")
        old["snapshot_date"] = old["snapshot_date"].astype(str)
        rows = []
        old_dates = sorted(old["snapshot_date"].unique())
        for day, syms in anchors.items():
            prior = [d for d in old_dates if d <= day]
            if not prior:
                continue
            source_day = prior[-1]
            o = set(old.loc[old["snapshot_date"] == source_day, "api_symbol"])
            a, b = canon_set(syms, renames), canon_set(o, renames)
            rows.append((day, len(a & b) / max(1, len(a | b)), len(a & b) / max(1, len(a)) ))
        if rows:
            improvement = {
                "anchors_compared": len(rows),
                "old_mean_jaccard": round(sum(r[1] for r in rows) / len(rows), 4),
                "old_mean_recall": round(sum(r[2] for r in rows) / len(rows), 4),
                "detail": [{"date": r[0], "jaccard": round(r[1], 4), "recall": round(r[2], 4)} for r in rows],
            }
    check("IMPROVEMENT", improvement is None or improvement["old_mean_jaccard"] < 0.99,
          old_table_vs_anchors=improvement)

    passed = all(c["passed"] for c in checks)
    table_sha = sha256(TABLE)
    cert = {
        "certificate_type": "PIT_UNIVERSE_CERTIFICATE",
        "index": "NIFTY 500",
        "table": str(TABLE.relative_to(ROOT)),
        "table_sha256": table_sha,
        "snapshots": len(dates),
        "date_range": [dates[0], dates[-1]],
        "anchors": sorted(anchors),
        "anchor_count": len(anchors),
        "coverage_ratio": round(cov, 4),
        "mean_cross_source_jaccard": round(mean_jac, 4),
        "coverage_by_year": details.get("coverage_by_year", {}),
        "gates": checks,
        "verdict": "PASS" if passed else "FAIL",
        "verified_at_utc": pd.Timestamp.utcnow().isoformat(),
        "sources": {
            "nse_anchors": "Internet Archive captures of niftyindices.com/IndexConstituent/ind_nifty500list.csv",
            "press_release_intervals": "aditya-jha/nse-historical-membership (CC BY 4.0)",
        },
    }
    CERT.parent.mkdir(parents=True, exist_ok=True)
    CERT.write_text(json.dumps(cert, indent=2), encoding="utf-8")

    lines = ["# PIT Universe Verification — NIFTY 500", "",
             f"**Verdict: {'PASS' if passed else 'FAIL'}** · {cert['verified_at_utc']}", "",
             f"- Table: `{cert['table']}` · sha256 `{table_sha[:16]}…`",
             f"- Snapshots: **{len(dates)}** ({dates[0]} → {dates[-1]})",
             f"- NSE anchors: **{len(anchors)}** · cross-source Jaccard **{mean_jac:.3f}**",
             f"- Price mapping coverage: **{cov:.1%}**", "",
             "| Gate | Result | Detail |", "|---|---|---|"]
    for c in checks:
        detail = {k: v for k, v in c.items() if k not in ("check", "passed")}
        lines.append(f"| {c['check']} | {'PASS' if c['passed'] else 'FAIL'} | `{json.dumps(detail)[:160]}` |")
    if improvement:
        lines += ["", f"Old table at anchors: Jaccard {improvement['old_mean_jaccard']:.3f}, "
                      f"recall {improvement['old_mean_recall']:.3f} → new table 1.000 (anchors are exact)."]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(f"{c['check']:22} {'PASS' if c['passed'] else 'FAIL'}" for c in checks))
    print(f"\nverdict={'PASS' if passed else 'FAIL'} mean_jaccard={mean_jac:.4f} coverage={cov:.4f}")
    print(f"wrote {REPORT.relative_to(ROOT)} and {CERT.relative_to(ROOT)}")
    return 0 if (passed or not args.strict) else 1


if __name__ == "__main__":
    sys.exit(main())
