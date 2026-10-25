"""Point-in-time NSE index membership.

Primary source: ``data/pit_constituents/nifty500_snapshots.csv``, rebuilt by
``scripts/build_pit_membership.py`` from **17 exact NSE NIFTY 500 constituent
files recovered from the Internet Archive** (2018-10-04 → 2026-10-22). Dates
between anchors walk forward from the previous anchor through the CC BY 4.0
``nse-historical-membership`` press-release event log; every later anchor snaps
the walk, so error cannot accumulate. Dates before the first anchor use the
interval table directly.

Between snapshot dates the latest snapshot on or before the date is used, so a
backtest uses the constituents that existed on each rebalance date, not today's
list. Interval semantics for non-snapshot indices are half-open
``[valid_from, valid_to)``.

Verification and provenance: ``reports/PIT_VERIFICATION.md`` and
``certificates/PIT_UNIVERSE_CERTIFICATE.json``. The older niftyhistory.in table
is kept only as ``nifty500_snapshots.csv.bak`` and scored 0.71 Jaccard against
the NSE anchors; do not use it for research.
"""
from __future__ import annotations

import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

import numpy as np
import pandas as pd

PIT_DIR = "data/pit_constituents"


def _norm(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _base(base_dir: Optional[Path]) -> Path:
    if base_dir is None:
        from core.data_engine import get_base_dir
        return Path(get_base_dir())
    return Path(base_dir)


@lru_cache(maxsize=8)
def _load_intervals(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["valid_from"] = pd.to_datetime(df["valid_from"], errors="coerce")
    df["valid_to"] = pd.to_datetime(df["valid_to"], errors="coerce")
    df = df[df["valid_from"].notna()].copy()
    df["symbol"] = df["symbol"].astype(str).str.upper().str.strip()
    df["_index_norm"] = df["index_name"].map(_norm)
    return df


@lru_cache(maxsize=8)
def _load_snapshots(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce")
    df = df[df["snapshot_date"].notna()].copy()
    df["api_symbol"] = df["api_symbol"].astype(str).str.upper().str.strip()
    df["db_symbol"] = df["db_symbol"].astype("string").fillna("").str.strip()
    return df.sort_values("snapshot_date")


@lru_cache(maxsize=8)
def _snapshot_dates(path: str):
    df = _load_snapshots(path)
    return sorted(df["snapshot_date"].dropna().unique())


@lru_cache(maxsize=8)
def _index_alias_map(path: str) -> Dict[str, str]:
    df = _load_intervals(path)
    return {row["_index_norm"]: row["index_name"] for _, row in df.drop_duplicates("_index_norm").iterrows()}


@lru_cache(maxsize=8)
def _renames(path: str) -> Dict[str, str]:
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    out = {}
    for r in data.get("renames", []):
        old, new = str(r.get("old") or "").upper(), str(r.get("new") or "").upper()
        if old and new and not new.startswith("_"):
            out[old] = new
    return out


def _paths(base_dir: Optional[Path]):
    base = _base(base_dir)
    return (
        str(base / PIT_DIR / "index_membership_history.csv"),
        str(base / PIT_DIR / "symbol_renames.json"),
    )


def _snapshot_path(base_dir: Optional[Path] = None) -> str:
    return str(_base(base_dir) / PIT_DIR / "nifty500_snapshots.csv")


def _latest_snapshot(date: str, base_dir: Optional[Path] = None):
    import bisect
    path = _snapshot_path(base_dir)
    if not Path(path).exists():
        return None, None
    dates = _snapshot_dates(path)
    j = bisect.bisect_right(dates, pd.Timestamp(date)) - 1
    if j < 0:
        return None, None
    return dates[j], path


def available_indices(base_dir: Optional[Path] = None) -> List[str]:
    csv_path, _ = _paths(base_dir)
    if not Path(csv_path).exists():
        return []
    return sorted(set(_load_intervals(csv_path)["index_name"].astype(str)))


def has_coverage(
    index_name: str,
    start_date: str,
    end_date: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> bool:
    """True if a PIT snapshot table overlaps [start_date, end_date]."""
    path = _snapshot_path(base_dir)
    if _use_snapshots(index_name, base_dir):
        dates = _snapshot_dates(path)
        if dates:
            s, e = pd.Timestamp(start_date), pd.Timestamp(end_date or start_date)
            return dates[0] <= e and dates[-1] >= s
    csv_path, _ = _paths(base_dir)
    if not Path(csv_path).exists():
        return False
    df = _load_intervals(csv_path)
    sub = df[df["_index_norm"] == _norm(index_name)]
    if sub.empty:
        return False
    s, e = pd.Timestamp(start_date), pd.Timestamp(end_date or start_date)
    overlap = sub[(sub["valid_from"] <= e) & (sub["valid_to"].isna() | (sub["valid_to"] > s))]
    return not overlap.empty


def _use_snapshots(index_name: str, base_dir: Optional[Path] = None) -> bool:
    """The snapshot table is NIFTY500-specific."""
    return _norm(index_name) == "NIFTY500" and Path(_snapshot_path(base_dir)).exists()


def _snapshot_members(as_of_date: str, base_dir: Optional[Path] = None):
    """(snapshot_date, api_symbols, db_symbols) for the latest snapshot <= date."""
    d, path = _latest_snapshot(as_of_date, base_dir)
    if d is None:
        return None, set(), set()
    df = _load_snapshots(path)
    rows = df[df["snapshot_date"] == d]
    api = set(rows["api_symbol"].astype(str))
    db = {s for s in rows["db_symbol"].astype(str) if s}
    return d, api, db


def members_as_of(index_name: str, as_of_date: str, base_dir: Optional[Path] = None) -> Set[str]:
    """Member symbols on a date (API/canonical names)."""
    if _use_snapshots(index_name, base_dir):
        _, api, _ = _snapshot_members(as_of_date, base_dir)
        return api
    csv_path, _ = _paths(base_dir)
    df = _load_intervals(csv_path)
    sub = df[df["_index_norm"] == _norm(index_name)]
    if sub.empty:
        return set()
    t = pd.Timestamp(as_of_date)
    m = sub[(sub["valid_from"] <= t) & (sub["valid_to"].isna() | (sub["valid_to"] > t))]
    return set(m["symbol"])


def db_symbols(base_dir: Optional[Path] = None) -> List[str]:
    base = _base(base_dir)
    db = base / "data" / "universe.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return sorted({r[0] for r in con.execute("SELECT DISTINCT symbol FROM prices")})
    finally:
        con.close()


def identity_map(base_dir: Optional[Path] = None) -> Dict[str, str]:
    """DB symbol -> canonical terminal symbol (old names collapse to the new one)."""
    _, ren_path = _paths(base_dir)
    ren = _renames(ren_path)
    return {s: ren.get(s, s) for s in db_symbols(base_dir)}


def members_db_as_of(
    index_name: str,
    as_of_date: str,
    base_dir: Optional[Path] = None,
    symbols: Optional[Sequence[str]] = None,
    identity: Optional[Dict[str, str]] = None,
) -> Set[str]:
    """DB symbols that are members on the date."""
    if _use_snapshots(index_name, base_dir):
        _, _, db = _snapshot_members(as_of_date, base_dir)
        return set(db) if symbols is None else {s for s in symbols if s in db}
    mem = members_as_of(index_name, as_of_date, base_dir)
    if not mem:
        return set()
    idmap = identity if identity is not None else identity_map(base_dir)
    pool = symbols if symbols is not None else idmap.keys()
    return {s for s in pool if idmap.get(s, s) in mem}


def union_members_db(
    index_name: str,
    start_date: str,
    end_date: str,
    base_dir: Optional[Path] = None,
) -> List[str]:
    """Every DB symbol that was a member at any point in the window."""
    if _use_snapshots(index_name, base_dir):
        path = _snapshot_path(base_dir)
        df = _load_snapshots(path)
        s, e = pd.Timestamp(start_date), pd.Timestamp(end_date)
        dates = _snapshot_dates(path)
        import bisect
        j = bisect.bisect_right(dates, s) - 1
        keep = set(dates[max(j, 0):])
        keep = {d for d in keep if d <= e}
        sub = df[df["snapshot_date"].isin(keep)]
        return sorted({x for x in sub["db_symbol"].astype(str) if x})
    csv_path, _ = _paths(base_dir)
    df = _load_intervals(csv_path)
    sub = df[df["_index_norm"] == _norm(index_name)]
    if sub.empty:
        return []
    s, e = pd.Timestamp(start_date), pd.Timestamp(end_date)
    overlap = sub[(sub["valid_from"] < e) & (sub["valid_to"].isna() | (sub["valid_to"] > s))]
    canonical = set(overlap["symbol"])
    idmap = identity_map(base_dir)
    return sorted({sym for sym, canon in idmap.items() if canon in canonical})


def membership_mask(
    index_name: str,
    dates: Sequence[str],
    symbols: Sequence[str],
    base_dir: Optional[Path] = None,
) -> np.ndarray:
    """[T, N] uint8 mask: 1 when symbols[j] is a member on dates[i]."""
    import bisect

    mask = np.zeros((len(dates), len(symbols)), dtype=np.uint8)
    if _use_snapshots(index_name, base_dir):
        path = _snapshot_path(base_dir)
        boundaries = _snapshot_dates(path)
        if not boundaries:
            return mask
        cache: Dict[pd.Timestamp, Set[str]] = {}
        for i, d in enumerate(dates):
            t = pd.Timestamp(d)
            j = bisect.bisect_right(boundaries, t) - 1
            if j < 0:
                continue
            b = boundaries[j]
            mem = cache.get(b)
            if mem is None:
                mem = set(_snapshot_members(b.strftime("%Y-%m-%d"), base_dir)[2])
                cache[b] = mem
            if not mem:
                continue
            mask[i] = np.fromiter((s in mem for s in symbols), dtype=np.uint8, count=len(symbols))
        return mask

    csv_path, _ = _paths(base_dir)
    df = _load_intervals(csv_path)
    sub = df[df["_index_norm"] == _norm(index_name)]
    boundaries = sorted(set(sub["valid_from"]) | set(sub["valid_to"].dropna()))
    idmap = identity_map(base_dir)
    canon = [idmap.get(s, s) for s in symbols]
    if not boundaries:
        return mask
    cache = {}
    for i, d in enumerate(dates):
        t = pd.Timestamp(d)
        j = bisect.bisect_right(boundaries, t) - 1
        if j < 0:
            continue
        boundary = boundaries[j]
        mem = cache.get(boundary)
        if mem is None:
            mem = members_as_of(index_name, boundary.strftime("%Y-%m-%d"), base_dir)
            cache[boundary] = mem
        if not mem:
            continue
        mask[i] = np.fromiter((c in mem for c in canon), dtype=np.uint8, count=len(canon))
    return mask


def coverage_stats(
    index_name: str,
    as_of_date: str,
    min_bars: int = 252,
    base_dir: Optional[Path] = None,
) -> Dict[str, object]:
    """Membership and data-availability counts at a date."""
    base = _base(base_dir)
    api_members = members_as_of(index_name, as_of_date, base_dir)
    mapped = members_db_as_of(index_name, as_of_date, base_dir)
    con = sqlite3.connect(f"file:{base/'data'/'universe.db'}?mode=ro", uri=True)
    try:
        counts = {r[0]: r[1] for r in con.execute(
            "SELECT symbol, COUNT(*) FROM prices WHERE date<=? GROUP BY symbol", (as_of_date,))}
    finally:
        con.close()
    eligible = {s for s in mapped if counts.get(s, 0) >= int(min_bars)}
    return {
        "index": index_name,
        "as_of": as_of_date,
        "members": len(mapped),
        "api_members": len(api_members),
        "db_symbols_mapped": len(mapped),
        "eligible_symbols": len(eligible),
        "coverage_pct_of_members": round(len(eligible) / max(len(api_members), 1) * 100, 2),
        "min_bars": int(min_bars),
    }
