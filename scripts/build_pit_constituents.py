"""Build the primary PIT membership table from niftyhistory.in snapshots.

Input (committed):
  data/pit_constituents/verification/niftyhistory_500_YYYY.csv
  (full Nifty 500 constituent lists at each rebalancing effective date)

Output:
  data/pit_constituents/nifty500_snapshots.csv
      snapshot_date, api_symbol, db_symbol
  data/pit_constituents/nifty500_snapshots_meta.json

The niftyhistory symbol column mixes NSE tickers with truncated/old names. Each
name is mapped to a DB symbol by exact, alias, then prefix match. Unmapped names
are kept in the CSV with an empty db_symbol and counted in the metadata.

The repo interval table (CC BY 4.0) remains as a secondary cross-check.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
PIT = ROOT / "data" / "pit_constituents"
VER = PIT / "verification"
DB = ROOT / "data" / "universe.db"

ALIASES = {
    "RELIANCEHO": "RHFL", "SECURITYAN": "SIS", "SINTEXPLAS": "SPTL",
    "BOMBAYRAYO": "BRFL", "HOUSINGDEV": "HDIL", "BHUSHANSTE": "BHUSANSTL",
    "CAPITALFIR": "CAPF", "IIFLHOLDIN": "IIFL", "HINDUJAGLO": "HINDJAGL",
    "TATVACHINT": "TATVA", "BAJAJHINDU": "BAJAJHIND", "ABANOFFSHO": "ABAN",
    "BALLARPURI": "BALLARPUR", "EXCELCROPC": "EXCELCROP",
    "OLAELECTRI": "OLAELEC", "HONASACONS": "HONASA", "TECHNOELTE": "TECHNO",
    "COXKINGS": "COX&KINGS", "GARDENREAC": "GARDENREACH",
    "GUJARATFLU": "GUJARATFLUORO", "INDIANRAIL": "IRCTC",
    "SUMITOMOCH": "SUMICHEM", "UJJIVANSMA": "UJJIVANSFB",
    "DEWANHOUSI": "DHFL", "LAKSHMIVIL": "LAKSHMI",
    "SHKELKARAN": "SHKELKAR", "PRUDENTCOR": "PRUDENT", "SYRMASGS": "SYRMA",
    "FUTURECONS": "FUTCON", "SPANDANASP": "SPANDANA",
    "BRAINBEESS": "BRAINBEES", "UNICOMMERC": "UNICOMMERCE",
}


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def main():
    import sqlite3

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db_symbols = sorted({r[0] for r in con.execute("SELECT DISTINCT symbol FROM prices")})
    con.close()
    db_norm = {}
    for s in db_symbols:
        db_norm.setdefault(norm(s), s)

    def map_to_db(api: str):
        a = str(api).strip().upper()
        key = norm(ALIASES.get(a, a))
        if key in db_norm:
            return db_norm[key]
        candidates = [s for s in db_symbols if norm(s).startswith(key) or key.startswith(norm(s))]
        candidates = [c for c in candidates if len(norm(c)) >= 4 and len(key) >= 4]
        if not candidates:
            return ""
        candidates.sort(key=lambda c: (abs(len(norm(c)) - len(key)), len(c)))
        return candidates[0]

    rows = []
    files = sorted(VER.glob("niftyhistory_500_*.csv"))
    if not files:
        raise SystemExit("No niftyhistory snapshot CSVs found.")
    for f in files:
        df = pd.read_csv(f)
        for _, ev in df.iterrows():
            d = str(ev["effective_date"])
            api_syms = [s.strip().upper() for s in str(ev["symbols"]).split(",") if s.strip()]
            for s in api_syms:
                rows.append({"snapshot_date": d, "api_symbol": s, "db_symbol": map_to_db(s)})

    out = pd.DataFrame(rows).drop_duplicates(["snapshot_date", "api_symbol"])
    out.to_csv(PIT / "nifty500_snapshots.csv", index=False)

    per_date = out.groupby("snapshot_date").agg(
        api_symbols=("api_symbol", "nunique"),
        mapped=("db_symbol", lambda s: int((s != "").sum())),
        unique_db=("db_symbol", lambda s: int(len({x for x in s if x}))),
    ).reset_index()
    meta = {
        "source": "https://niftyhistory.in/",
        "source_endpoint": "/download?index_type=Nifty 500",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "files": [f.name for f in files],
        "snapshots": int(out["snapshot_date"].nunique()),
        "api_symbols": int(out["api_symbol"].nunique()),
        "mapped_to_db": int((out["db_symbol"] != "").sum()),
        "unmapped": int((out["db_symbol"] == "").sum()),
        "per_date": per_date.to_dict(orient="records"),
        "note": "Primary PIT source. The CC BY 4.0 repo interval table is kept as a secondary cross-check.",
    }
    (PIT / "nifty500_snapshots_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({k: meta[k] for k in ("snapshots", "api_symbols", "mapped_to_db", "unmapped")}, indent=2))
    print(per_date.to_string(index=False))


if __name__ == "__main__":
    main()
