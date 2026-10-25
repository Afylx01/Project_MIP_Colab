#!/usr/bin/env python3
"""Build the point-in-time NIFTY 500 membership table.

Design
------
Membership is reconstructed from two independent, auditable inputs:

1. ``data/pit_constituents/anchors/ind_nifty500list_YYYYMMDD.csv``
   Exact NSE-published constituent files recovered from the Internet Archive
   (one file per capture). These are ground truth on their capture date.
2. ``data/pit_constituents/index_membership_history.csv``
   CC BY 4.0 interval table derived from NSE press releases by
   https://github.com/aditya-jha/nse-historical-membership
   (commit pinned in metadata.json). Used for every date without an anchor.

Rule of precedence: an anchor always wins on its own date. On other dates the
interval table is used. Symbols are canonicalised through
``data/pit_constituents/symbol_renames.json`` (old ticker -> terminal ticker)
and then mapped back to the ticker that actually has a price series in
``data/universe.db`` on that date, so the result is directly tradeable.

Output: ``data/pit_constituents/nifty500_snapshots.csv`` with columns
``snapshot_date,api_symbol,db_symbol`` (the schema consumed by
``core/pit_membership.py``), plus ``nifty500_snapshots_meta.json``.

Usage
-----
    python3 scripts/build_pit_membership.py            # rebuild in place
    python3 scripts/build_pit_membership.py --check    # verify, write nothing
    python3 scripts/build_pit_membership.py --start 2016-01-01
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PIT = ROOT / "data" / "pit_constituents"
ANCHOR_DIR = PIT / "anchors"
INTERVALS = PIT / "index_membership_history.csv"
EVENTS = PIT / "nifty500_events.csv"
RENAMES = PIT / "symbol_renames.json"
OUT_CSV = PIT / "nifty500_snapshots.csv"
OUT_META = PIT / "nifty500_snapshots_meta.json"
DB = ROOT / "data" / "universe.db"

INDEX_NAME = "Nifty 500"
PRICE_MATCH_DAYS = 10          # a DB ticker counts as live if it traded this close
MAX_CARDINALITY_DRIFT = 12     # NIFTY 500 legitimately holds 499-504 names


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_renames() -> Dict[str, str]:
    """old ticker -> terminal ticker. First mapping wins (no identity rows)."""
    out: Dict[str, str] = {}
    for row in json.loads(RENAMES.read_text())["renames"]:
        old = str(row.get("old") or "").strip().upper()
        new = str(row.get("new") or "").strip().upper()
        if not old or not new or new.startswith("_"):
            continue
        if old == new:
            continue
        out.setdefault(old, new)
    # Collapse chains.
    for old in list(out):
        seen, cur = {old}, out[old]
        while cur in out and cur not in seen:
            seen.add(cur)
            cur = out[cur]
        out[old] = cur
    return out


def load_renames_dated() -> List[Tuple[str, str, str]]:
    """(effective_date, old, new) for renames that carry a usable date."""
    out: List[Tuple[str, str, str]] = []
    for row in json.loads(RENAMES.read_text())["renames"]:
        old = str(row.get("old") or "").strip().upper()
        new = str(row.get("new") or "").strip().upper()
        eff = str(row.get("effective_date") or "")[:10]
        if not old or not new or old == new or new.startswith("_"):
            continue
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", eff):
            out.append((eff, old, new))
    return sorted(out)


def load_anchors() -> Dict[str, List[str]]:
    anchors: Dict[str, List[str]] = {}
    for path in sorted(glob.glob(str(ANCHOR_DIR / "ind_nifty500list_*.csv"))):
        m = re.search(r"ind_nifty500list_(\d{8})\.csv$", path)
        if not m:
            continue
        d = m.group(1)
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        symbols: List[str] = []
        text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
        for line in text.splitlines()[1:]:
            parts = line.split(",")
            if len(parts) >= 3 and parts[2].strip():
                symbols.append(parts[2].strip().upper())
        if symbols:
            anchors[iso] = symbols
    return anchors


def load_events() -> List[Dict[str, object]]:
    """Press-release inclusion/exclusion events for NIFTY 500, canonicalised."""
    if not EVENTS.exists():
        return []
    df = pd.read_csv(EVENTS, dtype=str).fillna("")
    out: List[Dict[str, object]] = []
    for row in df.itertuples():
        out.append({
            "date": str(row.effective_date)[:10],
            "excluded": {s.strip().upper() for s in row.excluded.split("|") if s.strip()},
            "included": {s.strip().upper() for s in row.included.split("|") if s.strip()},
            "source_pdf": row.source_pdf,
        })
    return sorted(out, key=lambda e: e["date"])


def load_intervals() -> pd.DataFrame:
    df = pd.read_csv(INTERVALS)
    df = df[df["index_name"] == INDEX_NAME].copy()
    df["valid_from"] = pd.to_datetime(df["valid_from"], errors="coerce")
    df["valid_to"] = pd.to_datetime(df["valid_to"], errors="coerce")
    return df[df["valid_from"].notna()]


def interval_members(df: pd.DataFrame, day: str) -> List[str]:
    t = pd.Timestamp(day)
    active = df[(df["valid_from"] <= t) & (df["valid_to"].isna() | (df["valid_to"] > t))]
    return sorted(set(active["symbol"].astype(str).str.upper()))


def db_ranges() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(
            "SELECT symbol, MIN(date) AS first_date, MAX(date) AS last_date, COUNT(*) AS bars "
            "FROM prices GROUP BY symbol",
            con,
        )
    finally:
        con.close()


def canonical(sym: str, renames: Dict[str, str]) -> str:
    seen = set()
    while sym in renames and sym not in seen:
        seen.add(sym)
        sym = renames[sym]
    return sym


def build_db_index(ranges: pd.DataFrame, renames: Dict[str, str]) -> Dict[str, List[Tuple[str, str, str]]]:
    index: Dict[str, List[Tuple[str, str, str]]] = {}
    for row in ranges.itertuples():
        index.setdefault(canonical(row.symbol, renames), []).append(
            (row.symbol, row.first_date, row.last_date)
        )
    return index


def map_to_db(sym: str, day: str, index: Dict[str, List[Tuple[str, str, str]]],
              renames: Dict[str, str]) -> str:
    """Pick the DB ticker for a member (raw or canonical) that is live on ``day``."""
    day_ts = pd.Timestamp(day)
    tol = pd.Timestamp(day) - timedelta(days=PRICE_MATCH_DAYS)

    def live(symbol: str) -> Optional[str]:
        for db_symbol, first, last in index.get(symbol, []):
            f, l = pd.Timestamp(first), pd.Timestamp(last)
            if f <= day_ts and l >= tol:
                if db_symbol == sym:
                    return db_symbol
        for db_symbol, first, last in index.get(symbol, []):
            f, l = pd.Timestamp(first), pd.Timestamp(last)
            if f <= day_ts and l >= tol:
                return db_symbol
        return None

    direct = live(sym)
    if direct:
        return direct
    if renames:
        return live(canonical(sym, renames)) or ""
    return ""


def month_ends(start: str, end: str) -> List[str]:
    days = pd.date_range(start=start, end=end, freq="ME")
    return [d.strftime("%Y-%m-%d") for d in days]


def plan_dates(anchors: Dict[str, List[str]], start: str, end: str) -> List[str]:
    existing = pd.read_csv(OUT_CSV, usecols=["snapshot_date"])["snapshot_date"].astype(str)
    dates = set(existing) | set(anchors) | set(month_ends(start, end))
    return sorted(d for d in dates if start <= d <= max(end, max(anchors)))


def build(start: str, end: str) -> Tuple[pd.DataFrame, Dict]:
    renames = load_renames()
    anchors = load_anchors()
    if not anchors:
        raise SystemExit("no anchor files found in data/pit_constituents/anchors/")
    intervals = load_intervals()
    index = build_db_index(db_ranges(), renames)

    events = load_events()
    dated_renames = load_renames_dated()
    dummy_prefixes = ("DUMMY", "_DUMMY")

    def is_dummy(sym: str) -> bool:
        return sym.startswith(dummy_prefixes)

    anchor_sets = {
        d: {s for s in syms if not is_dummy(s)}
        for d, syms in anchors.items()
    }
    first_anchor = min(anchor_sets)
    anchor_dates = sorted(anchor_sets)

    def walk(base_date: str, base_set: Set[str], day: str) -> Set[str]:
        """Advance a raw-ticker membership set from base_date to day.

        Applies dated ticker renames, then index inclusion/exclusion events.
        Anchors are exact NSE publications and are snapped on their own date.
        """
        out = set(base_set)
        for eff, old, new in dated_renames:
            if base_date < eff <= day and old in out:
                out.discard(old)
                out.add(new)
        for ev in events:
            if base_date < ev["date"] <= day:
                for x in ev["excluded"]:  # type: ignore[union-attr]
                    out.discard(x)
                for x in ev["included"]:  # type: ignore[union-attr]
                    out.add(x)
        return {x for x in out if not is_dummy(x)}

    rows = []
    sources = []
    for day in plan_dates(anchors, start, end):
        if day in anchor_sets:
            members, source = anchor_sets[day], "nse_wayback_anchor"
        elif day > first_anchor:
            prev = [d for d in anchor_dates if d <= day][-1]
            members, source = walk(prev, anchor_sets[prev], day), "anchor_plus_press_releases"
        else:
            members = {canonical(s, renames) for s in interval_members(intervals, day)}
            members = {x for x in members if not is_dummy(x)}
            source = "press_release_intervals"
        for sym in sorted(members):
            rows.append((day, sym, map_to_db(sym, day, index, renames)))
        sources.append((day, source, len(members)))

    df = pd.DataFrame(rows, columns=["snapshot_date", "api_symbol", "db_symbol"])
    df = df.drop_duplicates(subset=["snapshot_date", "api_symbol"]).sort_values(
        ["snapshot_date", "api_symbol"]
    ).reset_index(drop=True)

    per_date = {}
    for day, g in df.groupby("snapshot_date"):
        per_date[day] = {
            "members": int(len(g)),
            "mapped": int((g["db_symbol"] != "").sum()),
            "unmapped": int((g["db_symbol"] == "").sum()),
            "source": dict((d, s) for d, s, _ in sources).get(day, "unknown"),
        }

    meta = {
        "source": "NSE Internet Archive anchors + aditya-jha/nse-historical-membership PR intervals",
        "index": INDEX_NAME,
        "schema": ["snapshot_date", "api_symbol", "db_symbol"],
        "built_at_utc": pd.Timestamp.utcnow().isoformat(),
        "start": start,
        "end": end,
        "snapshots": int(df["snapshot_date"].nunique()),
        "rows": int(len(df)),
        "anchors": sorted(anchors),
        "anchor_count": len(anchors),
        "mapped_rows": int((df["db_symbol"] != "").sum()),
        "unmapped_rows": int((df["db_symbol"] == "").sum()),
        "interval_table_sha256": sha256(INTERVALS),
        "events_table_sha256": sha256(EVENTS) if EVENTS.exists() else None,
        "method": "canonical tickers; anchor dates exact; dates after the first anchor walk "
                  "forward from the previous anchor through NSE press-release events; dates "
                  "before the first anchor fall back to the CC BY 4.0 interval table.",
        "renames_sha256": sha256(RENAMES),
        "anchor_files": {
            os.path.basename(p): sha256(Path(p))
            for p in sorted(glob.glob(str(ANCHOR_DIR / "ind_nifty500list_*.csv")))
        },
        "per_date": per_date,
        "caveats": [
            "Anchor dates are exact NSE publications and override every other source.",
            "Dates after 2018-10-04 walk forward from an exact NSE anchor through press-release "
            "events (tier B). Dates before the first anchor are interval-derived (tier C) and "
            "carry residual uncertainty because pre-2018 PR coverage is thinner.",
            "db_symbol is empty when no price series exists in universe.db for that member/date; "
            "the member is still counted in the index, but a backtest cannot trade it.",
        ],
    }
    return df, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    ap.add_argument("--check", action="store_true", help="build in memory and report, write nothing")
    args = ap.parse_args()

    df, meta = build(args.start, args.end)

    bad = []
    for day, g in df.groupby("snapshot_date"):
        n = len(g)
        if not (500 - MAX_CARDINALITY_DRIFT <= n <= 500 + MAX_CARDINALITY_DRIFT):
            bad.append(f"{day}: cardinality {n}")
        if g["api_symbol"].duplicated().any():
            bad.append(f"{day}: duplicate api_symbol")
    if bad:
        print("CARDINALITY / DUPLICATE PROBLEMS:")
        print("\n".join(bad[:20]))
        return 2

    print(f"snapshots={meta['snapshots']} rows={meta['rows']} "
          f"anchors={meta['anchor_count']} mapped={meta['mapped_rows']} unmapped={meta['unmapped_rows']}")
    if args.check:
        print("check mode: nothing written")
        return 0

    backup = OUT_CSV.with_suffix(".csv.bak")
    if OUT_CSV.exists() and not backup.exists():
        backup.write_bytes(OUT_CSV.read_bytes())
        print(f"backed up previous table -> {backup.name}")

    tmp = OUT_CSV.with_suffix(".csv.tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(OUT_CSV)
    OUT_META.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"wrote {OUT_CSV} ({OUT_CSV.stat().st_size:,} bytes)")
    print(f"wrote {OUT_META}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
