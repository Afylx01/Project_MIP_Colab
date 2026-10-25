"""Regression gates for the rebuilt NIFTY 500 PIT membership table.

These are data-contract tests, not strategy tests: they fail if a future
rebuild silently loses an NSE anchor, leaks a DUMMY* scrip into the tradable
universe, or drifts away from a 500-name index.
"""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PIT = ROOT / "data" / "pit_constituents"
TABLE = PIT / "nifty500_snapshots.csv"
ANCHORS = PIT / "anchors"


def _table() -> pd.DataFrame:
    df = pd.read_csv(TABLE, dtype=str).fillna("")
    df["snapshot_date"] = df["snapshot_date"].astype(str)
    return df


def test_every_nse_anchor_is_reproduced_exactly():
    df = _table()
    anchor_files = sorted(ANCHORS.glob("ind_nifty500list_*.csv"))
    assert len(anchor_files) >= 12, "expected at least 12 independent NSE anchors"
    for path in anchor_files:
        day = path.stem.rsplit("_", 1)[1]
        iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        expected = {
            line.split(",")[2].strip().upper()
            for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[1:]
            if len(line.split(",")) >= 3 and line.split(",")[2].strip()
        }
        expected = {s for s in expected if not s.startswith("DUMMY")}
        got = set(df.loc[df["snapshot_date"] == iso, "api_symbol"].str.upper())
        assert got == expected, f"{iso}: table and NSE anchor disagree"


def test_no_dummy_placeholder_scrips_in_universe():
    df = _table()
    assert not df["api_symbol"].str.upper().str.startswith("DUMMY").any()


def test_cardinality_stays_within_index_tolerance():
    df = _table()
    counts = df.groupby("snapshot_date").size()
    assert counts.min() >= 488, f"snapshot with {counts.min()} members"
    assert counts.max() <= 512, f"snapshot with {counts.max()} members"


def test_snapshots_cover_the_canonical_backtest_window():
    df = _table()
    dates = df["snapshot_date"]
    assert dates.min() <= "2016-01-31"
    assert dates.max() >= "2026-09-30"
    assert not df.duplicated(["snapshot_date", "api_symbol"]).any()


def test_verifier_certificate_is_green():
    import json

    cert = ROOT / "certificates" / "PIT_UNIVERSE_CERTIFICATE.json"
    assert cert.exists(), "run scripts/verify_pit_membership.py"
    payload = json.loads(cert.read_text())
    assert payload["verdict"] == "PASS"
    failed = [g["check"] for g in payload["gates"] if not g["passed"]]
    assert not failed, f"failed gates: {failed}"
