"""Build point-in-time constituent snapshots for NIFTY 50 from 20Y weights dataset.

Source:
  https://huggingface.co/datasets/AMP4010/Historical_Nifty_50_Constituent_Weights_20Y
  Cached under data/pit_constituents/verification/nifty50_weights_amp4010.csv

Outputs:
  data/pit_constituents/nifty50_snapshots.csv
  data/pit_constituents/nifty50_snapshots_meta.json
"""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PIT = ROOT / "data" / "pit_constituents"
VER = PIT / "verification"
DB = ROOT / "data" / "universe.db"

# Aliases and canonical ticker mappings for NIFTY 50 members
NIFTY50_ALIASES = {
    "BAJAJAUTO": "BAJAJ-AUTO",
    "MCDOWELL-N": "UNITDSPR",
    "VSNL": "TATACOMM",
    "CAIRN": "VEDL",
    "SESAGOA": "VEDL",
    "STER": "VEDL",
    "IDFC": "IDFCFIRSTB",
    "RPL": "RELIANCE",
    "SATYAMCOMP": "TECHM",
    "RANBAXY": "SUNPHARMA",
}


def main():
    weights_path = VER / "nifty50_weights_amp4010.csv"
    if not weights_path.exists():
        raise FileNotFoundError(f"Missing {weights_path}")

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    db_symbols = set(pd.read_sql("SELECT DISTINCT symbol FROM prices", con)["symbol"])
    con.close()

    df = pd.read_csv(weights_path)
    all_syms = [c for c in df.columns if c != "DATE"]

    rows = []
    for _, row in df.iterrows():
        d = str(row["DATE"])
        active = [s for s in all_syms if float(row[s]) > 0]
        for s in active:
            # Map alias or exact DB symbol
            db_sym = s
            if s in NIFTY50_ALIASES:
                db_sym = NIFTY50_ALIASES[s]
            elif s not in db_symbols:
                db_sym = ""
            rows.append({
                "snapshot_date": d,
                "api_symbol": s,
                "db_symbol": db_sym,
                "weight_pct": round(float(row[s]), 5)
            })

    out = pd.DataFrame(rows).drop_duplicates(["snapshot_date", "api_symbol"])
    out.to_csv(PIT / "nifty50_snapshots.csv", index=False)

    per_date = out.groupby("snapshot_date").agg(
        api_symbols=("api_symbol", "nunique"),
        mapped=("db_symbol", lambda s: int((s != "").sum())),
        unique_db=("db_symbol", lambda s: int(len({x for x in s if x}))),
    ).reset_index()

    meta = {
        "source": "https://huggingface.co/datasets/AMP4010/Historical_Nifty_50_Constituent_Weights_20Y",
        "dataset_name": "AMP4010/Historical_Nifty_50_Constituent_Weights_20Y",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "snapshots": int(out["snapshot_date"].nunique()),
        "date_range": [str(out["snapshot_date"].min()), str(out["snapshot_date"].max())],
        "api_symbols": int(out["api_symbol"].nunique()),
        "mapped_to_db": int((out["db_symbol"] != "").sum()),
        "unmapped": int((out["db_symbol"] == "").sum()),
        "per_date": per_date.to_dict(orient="records"),
        "note": "Survivorship-bias-free 20Y monthly weights for NIFTY 50 constituents."
    }
    (PIT / "nifty50_snapshots_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"NIFTY 50 snapshots built: {meta['snapshots']} dates, {meta['mapped_to_db']} mapped rows, {meta['unmapped']} unmapped rows")


if __name__ == "__main__":
    main()
