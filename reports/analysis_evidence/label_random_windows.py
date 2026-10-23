"""Label every random rolling window VALID / DATA_INSUFFICIENT and recompute
summary statistics on the comparable subset.

Reads   reports/analysis_evidence/24_random_windows.csv
Writes  reports/analysis_evidence/24_random_windows_labelled.csv
        reports/analysis_evidence/33b_random_window_quality.json
"""
import json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
OUT = ROOT / "reports" / "analysis_evidence"
DB = ROOT / "data" / "universe.db"
MIN_HISTORY_PCT = 0.50
MIN_SESSIONS = 80


def main():
    import sys
    sys.path.insert(0, str(ROOT))
    from core.data_engine import load_universe_constituents
    syms = sorted(set(load_universe_constituents("NIFTY500")))
    q = ",".join("?" * len(syms))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    df = pd.read_csv(OUT / "24_random_windows.csv")
    covs, labels = [], []
    for _, r in df.iterrows():
        hist = con.execute(
            f"SELECT COUNT(*) FROM (SELECT symbol, COUNT(*) c FROM prices "
            f"WHERE symbol IN ({q}) AND date<=? GROUP BY symbol HAVING c>=252)",
            (*syms, r["end"])).fetchone()[0]
        sess = con.execute(
            "SELECT COUNT(DISTINCT date) FROM prices WHERE date>=? AND date<=?",
            (r["start"], r["end"])).fetchone()[0]
        pct = hist / len(syms)
        covs.append(round(pct * 100, 2))
        labels.append("VALID" if (pct >= MIN_HISTORY_PCT and sess >= MIN_SESSIONS) else "DATA_INSUFFICIENT")
    con.close()
    df["history_coverage_pct"] = covs
    df["label"] = labels
    df.to_csv(OUT / "24_random_windows_labelled.csv", index=False)

    def block(x):
        x = x[x["trades"] >= 20]
        if x.empty:
            return {"n": 0}
        return {
            "n": int(len(x)),
            "cagr_median": round(float(x["cagr"].median()), 2),
            "cagr_p05": round(float(x["cagr"].quantile(0.05)), 2),
            "cagr_p95": round(float(x["cagr"].quantile(0.95)), 2),
            "pct_positive": round(float((x["cagr"] > 0).mean() * 100), 1),
            "pct_beat_benchmark": round(float((x["excess"] > 0).mean() * 100), 1),
            "median_daily_maxdd_pct": round(float(x["maxdd"].median()), 2),
            "median_excess_pp": round(float(x["excess"].median()), 2),
        }

    out = {
        "rule": f">=252 bars by window end for >={int(MIN_HISTORY_PCT*100)}% of NIFTY500 and >={MIN_SESSIONS} sessions",
        "all_200": block(df),
        "valid_only": block(df[df.label == "VALID"]),
        "data_insufficient_only": block(df[df.label == "DATA_INSUFFICIENT"]),
        "modern_2016_plus_all": block(df[df.start >= "2016-01-01"]),
        "modern_2016_plus_valid": block(df[(df.start >= "2016-01-01") & (df.label == "VALID")]),
        "counts": {k: int(v) for k, v in df.label.value_counts().items()},
        "note": "maxdd column is the C-kernel DAILY intra-period drawdown; cagr uses sessions/252.",
    }
    (OUT / "33b_random_window_quality.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
