#!/usr/bin/env python3
"""Repair vendor segment artifacts in data/universe.db (backed by a ledger).

Two artifact classes are detected and fixed:

1. **Single-row spikes** — a bar whose close is far from *both* neighbours while
   the neighbours agree with each other. These are vendor row-level corruption
   (e.g. a Muhurat session quoted at a different scale). Fix: flatten OHLC to the
   previous close and set volume 0, so the row can never fill or signal.

2. **Vendor level shifts** — a *persistent* scale change arriving in a batch on
   one date (>= 10 symbols, next bar stable, no multi-year gap). These are the
   file-stitching boundaries of the price vendor. Fix: multiply all bars before
   the break by the break ratio, moving the older segment onto the current
   basis. Rows are never dropped; every edit is recorded in ``price_repairs``.

Deliberately NOT repaired:
  * isolated level shifts (real crashes, demergers, unregistered splits) —
    these are left for the corporate-action registry / anomaly gate;
  * post-gap resumptions (2026-09-01, 6-year hole) — recorded as
    ``resume_gap`` for quarantine by consumers.

Usage:
    python3 scripts/repair_price_series.py --dry-run
    MIP_ALLOW_PROD_MUTATION=1 python3 scripts/repair_price_series.py --apply
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

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "universe.db"
LEDGER = ROOT / "data" / "price_repairs.json"
SPIKE_THRESHOLD = 0.35
NEIGHBOUR_TOLERANCE = 0.20
BATCH_MIN = 10
MAX_GAP_DAYS = 60


def load() -> pd.DataFrame:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(
            "SELECT symbol, date, open, high, low, close, volume FROM prices WHERE close > 0 "
            "ORDER BY symbol, date", con)
    finally:
        con.close()


def detect(df: pd.DataFrame):
    g = df.groupby("symbol")["close"]
    prev, nxt = g.shift(1), g.shift(-1)
    r_prev, r_next, r_skip = df.close / prev - 1, df.close / nxt - 1, nxt / prev - 1
    spike = (r_prev.abs() > SPIKE_THRESHOLD) & (r_next.abs() > SPIKE_THRESHOLD) & (r_skip.abs() < NEIGHBOUR_TOLERANCE)

    # V-pattern: a recovery bar whose previous bar is an equally-sized corrupt
    # dip (product of the two ratios ~= 1). The corrupt bar is the previous one,
    # not the recovery, so flattening it is the correct repair.
    flat = df.copy()
    flat.loc[spike, "close"] = flat.loc[spike].index.map(prev)
    for col in ("open", "high", "low"):
        flat.loc[spike, col] = flat.loc[spike, "close"]
    flat.loc[spike, "volume"] = 0.0

    r = flat.groupby("symbol")["close"].pct_change()
    r_next_f = r.groupby(flat["symbol"]).shift(-1)
    day = pd.to_datetime(flat["date"])
    gap_days = day.groupby(flat["symbol"]).diff().dt.days

    candidates = flat[(r.abs() >= SPIKE_THRESHOLD)].copy()
    candidates["next_r"] = r_next_f[candidates.index]
    candidates["gap_days"] = gap_days[candidates.index]
    candidates["stable"] = candidates["next_r"].abs().fillna(1.0) < NEIGHBOUR_TOLERANCE
    candidates = candidates[candidates["stable"] & (candidates["gap_days"].fillna(999) <= MAX_GAP_DAYS)]

    counts = candidates.groupby("date").size()
    batch_dates = set()
    for day, grp in candidates[candidates["date"].isin(counts[counts >= BATCH_MIN].index)].groupby("date"):
        # vendor stitching moves prices by >=1.6x (or <=0.625x); a ~1.4x batch
        # is a market rebound, not a scale change.
        med = float(np.median(np.abs(np.log(1.0 + r[grp.index]))))
        if med > np.log(1.6):
            batch_dates.add(day)
    shifts = candidates[candidates["date"].isin(batch_dates)].copy()
    shifts["factor"] = 1.0 + r[shifts.index]

    resumes = flat[(gap_days > 365)].copy()
    return flat, df[spike], shifts, resumes, batch_dates


def plan_updates(df_orig, spikes, shifts):
    updates = []  # (symbol, date_from, date_to, factor)
    for sym, grp in shifts.groupby("symbol"):
        grp = grp.sort_values("date")
        dates = grp["date"].tolist()
        factors = grp["factor"].tolist()
        # cumulative factor for the segment before shift i = prod(factors[i:])
        cum = np.cumprod(factors[::-1])[::-1]
        boundaries = [None] + dates
        for i, start in enumerate(boundaries[:-1]):
            end = dates[i]
            updates.append((sym, None if start is None else start, end, float(cum[i])))
    return updates


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.apply and os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1":
        raise SystemExit("set MIP_ALLOW_PROD_MUTATION=1 to apply")

    df = load()
    flat, spikes, shifts, resumes, batch_dates = detect(df)
    updates = plan_updates(df, spikes, shifts)
    print(f"rows={len(df):,} symbols={df.symbol.nunique()}")
    print(f"single-row spikes: {len(spikes)} rows / {spikes.symbol.nunique()} symbols")
    print(f"vendor level shifts: {len(shifts)} events / {shifts.symbol.nunique()} symbols on {sorted(batch_dates)}")
    print(f"resume gaps (>365d): {len(resumes)} rows / {resumes.symbol.nunique()} symbols")
    print(f"segment update statements: {len(updates)}")

    ledger = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_sha256_before": hashlib.sha256(DB.read_bytes()).hexdigest(),
        "counts": {"spikes": int(len(spikes)), "shifts": int(len(shifts)),
                   "resumes": int(len(resumes)), "batch_dates": sorted(batch_dates)},
        "spikes": spikes[["symbol", "date"]].to_dict("records"),
        "shifts": shifts[["symbol", "date", "factor"]].assign(factor=lambda d: d.factor.round(8)).to_dict("records"),
        "resumes": resumes[["symbol", "date"]].drop_duplicates().to_dict("records"),
        "method": {
            "spike": "OHLC := previous close; volume := 0",
            "shift": "OHLC before break multiplied by break ratio (cumulative across shifts)",
            "excluded": "isolated level shifts (real events) and >365d resumptions are not repriced",
        },
    }
    if not args.apply:
        LEDGER.write_text(json.dumps(ledger, indent=2))
        print(f"dry run: wrote plan to {LEDGER.relative_to(ROOT)}")
        return 0

    con = sqlite3.connect(str(DB))
    try:
        con.execute("CREATE TABLE IF NOT EXISTS price_repairs ("
                    "symbol TEXT NOT NULL, date TEXT NOT NULL, kind TEXT NOT NULL, "
                    "factor REAL, prev_close REAL, note TEXT, applied_at TEXT, "
                    "PRIMARY KEY (symbol, date, kind))")
        con.execute("CREATE TABLE IF NOT EXISTS price_repair_manifest (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("BEGIN")
        now = datetime.now(timezone.utc).isoformat()
        # spikes: flatten to previous close
        prev_map = df.set_index(["symbol", "date"])["close"].shift(1)
        prev_series = df.groupby("symbol")["close"].shift(1)
        for idx, row in spikes.iterrows():
            pc = float(prev_series.loc[idx]) if pd.notna(prev_series.loc[idx]) else float(row["close"])
            con.execute("UPDATE prices SET open=?, high=?, low=?, close=?, volume=0 "
                        "WHERE symbol=? AND date=?", (pc, pc, pc, pc, row["symbol"], row["date"]))
            con.execute("INSERT OR REPLACE INTO price_repairs VALUES (?,?,?,?,?,?,?)",
                        (row["symbol"], row["date"], "spike_flatten", 1.0, pc,
                         "single-row vendor spike", now))
        # level shifts
        for sym, start, end, factor in updates:
            if start is None:
                con.execute("UPDATE prices SET open=open*?, high=high*?, low=low*?, close=close*? "
                            "WHERE symbol=? AND date < ?", (factor, factor, factor, factor, sym, end))
            else:
                con.execute("UPDATE prices SET open=open*?, high=high*?, low=low*?, close=close*? "
                            "WHERE symbol=? AND date >= ? AND date < ?",
                            (factor, factor, factor, factor, sym, start, end))
        for _, row in shifts.iterrows():
            con.execute("INSERT OR REPLACE INTO price_repairs VALUES (?,?,?,?,?,?,?)",
                        (row["symbol"], row["date"], "vendor_level_shift", float(row["factor"]), None,
                         "batch vendor scale change", now))
        manifest = {
            "repair_version": "1.0",
            "applied_at_utc": now,
            "spikes": str(len(spikes)),
            "shifts": str(len(shifts)),
            "batch_dates": ",".join(sorted(batch_dates)),
            "ledger_sha256": hashlib.sha256(json.dumps(ledger, sort_keys=True).encode()).hexdigest(),
        }
        con.executemany("INSERT OR REPLACE INTO price_repair_manifest VALUES (?,?)", list(manifest.items()))
        con.commit()
        check = con.execute("PRAGMA integrity_check").fetchone()[0]
        print("integrity_check:", check)
        if check != "ok":
            raise SystemExit("integrity check failed — restore data/universe.db.pre_repair_20261025")
    finally:
        con.close()

    ledger["db_sha256_after"] = hashlib.sha256(DB.read_bytes()).hexdigest()
    LEDGER.write_text(json.dumps(ledger, indent=2))
    print("db sha256 after:", ledger["db_sha256_after"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
