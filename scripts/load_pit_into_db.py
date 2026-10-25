#!/usr/bin/env python3
"""Load the verified PIT membership table into ``data/universe.db``.

Creates (idempotently):
  index_membership(index_name, symbol, db_symbol, valid_from, valid_to, source)
  pit_manifest(key, value)

``valid_from`` is inclusive, ``valid_to`` exclusive; NULL valid_to = still a
member at the last verified snapshot. Intervals are derived from the snapshot
table produced by ``scripts/build_pit_membership.py``.

The write is guarded by the production mutation firewall, so run with
``MIP_ALLOW_PROD_MUTATION=1``. A pre-change ``universe.db.bak`` must exist; the
script refuses to write otherwise.

Usage:
    MIP_ALLOW_PROD_MUTATION=1 python3 scripts/load_pit_into_db.py --write
    python3 scripts/load_pit_into_db.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "universe.db"
BAK = ROOT / "data" / "universe.db.bak"
PIT = ROOT / "data" / "pit_constituents"
TABLE = PIT / "nifty500_snapshots.csv"
CERT = ROOT / "certificates" / "PIT_UNIVERSE_CERTIFICATE.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_intervals() -> pd.DataFrame:
    t = pd.read_csv(TABLE, dtype=str).fillna("")
    t["snapshot_date"] = t["snapshot_date"].astype(str)
    dates = sorted(t["snapshot_date"].unique())
    idx = {d: i for i, d in enumerate(dates)}
    rows = []
    for sym, g in t.groupby("api_symbol"):
        present = {r.snapshot_date: r.db_symbol for r in g.itertuples()}
        start = None
        prev_i = None
        cur_db = None
        for i, d in enumerate(dates):
            if d in present:
                entry_db = present[d]
                if start is not None and prev_i == i - 1 and entry_db == cur_db:
                    prev_i = i
                    continue
                if start is not None:
                    rows.append((sym, cur_db, start, dates[prev_i]))
                start, prev_i, cur_db = d, i, entry_db
            else:
                if start is not None:
                    rows.append((sym, cur_db, start, d))
                    start = None
        if start is not None:
            rows.append((sym, cur_db, start, None))
    df = pd.DataFrame(rows, columns=["symbol", "db_symbol", "valid_from", "valid_to"])
    return df.sort_values(["valid_from", "symbol"]).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit(f"missing {DB}")
    if args.write and not BAK.exists():
        raise SystemExit("refusing to write: data/universe.db.bak rollback copy is missing")
    if args.write and os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1":
        raise SystemExit("set MIP_ALLOW_PROD_MUTATION=1 to write to universe.db")

    intervals = build_intervals()
    cert = json.loads(CERT.read_text())
    print(f"intervals={len(intervals):,} symbols={intervals.symbol.nunique()} "
          f"range={intervals.valid_from.min()}..{intervals.valid_from.max()}")

    if args.check:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            has = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='index_membership'"
            ).fetchone()
            print("index_membership present:", bool(has))
        finally:
            con.close()
        return 0

    con = sqlite3.connect(str(DB))
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("""
            CREATE TABLE IF NOT EXISTS index_membership (
                index_name TEXT NOT NULL,
                symbol     TEXT NOT NULL,
                db_symbol  TEXT,
                valid_from TEXT NOT NULL,
                valid_to   TEXT,
                source     TEXT NOT NULL DEFAULT 'NSE_ANCHOR_WALK',
                PRIMARY KEY (index_name, symbol, valid_from)
            )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_membership_lookup "
                    "ON index_membership(index_name, valid_from, valid_to)")
        con.execute("""
            CREATE TABLE IF NOT EXISTS pit_manifest (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
        con.execute("DELETE FROM index_membership WHERE index_name='NIFTY500'")
        con.executemany(
            "INSERT OR REPLACE INTO index_membership"
            "(index_name, symbol, db_symbol, valid_from, valid_to, source) "
            "VALUES ('NIFTY500', ?, ?, ?, ?, 'NSE_ANCHOR_WALK')",
            [(r.symbol, r.db_symbol, r.valid_from, r.valid_to) for r in intervals.itertuples()],
        )
        manifest = {
            "index_membership.nifty500.intervals": str(len(intervals)),
            "index_membership.nifty500.symbols": str(intervals.symbol.nunique()),
            "pit.snapshots": str(cert["snapshots"]),
            "pit.anchor_count": str(cert["anchor_count"]),
            "pit.verdict": cert["verdict"],
            "pit.certificate_sha256": sha256(CERT),
            "pit.table_sha256": sha256(TABLE),
            "pit.loaded_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        con.executemany("INSERT OR REPLACE INTO pit_manifest(key, value) VALUES (?, ?)",
                        list(manifest.items()))
        con.commit()
        check = con.execute("PRAGMA integrity_check").fetchone()[0]
        print("integrity_check:", check)
        if check != "ok":
            raise SystemExit("integrity check failed; rollback by restoring universe.db.bak")
        print(f"loaded intervals={len(intervals):,}")
    finally:
        con.close()

    print("database sha256:", sha256(DB))
    print("database bytes :", DB.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
