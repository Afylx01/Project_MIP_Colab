"""Label every random rolling window VALID / DATA_INSUFFICIENT.

The label uses the same breadth gate as the engines: a window is VALID only if
at least MIN_ELIGIBLE_SYMBOLS have the 252-bar history the strategy needs at
the window start. Coverage is measured against the whole price store (ALL),
not against a current index list.

Reads   reports/analysis_evidence/24_random_windows.csv
Writes  reports/analysis_evidence/24_random_windows_labelled.csv
        reports/analysis_evidence/33b_random_window_quality.json
"""
import json, sqlite3, sys
from pathlib import Path
import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
sys.path.insert(0, str(ROOT))
from core.pit_membership import coverage_stats
from core.universe_policy import min_pit_eligible
OUT = ROOT / "reports" / "analysis_evidence"
DB = ROOT / "data" / "universe.db"
MIN_ELIGIBLE_SYMBOLS = 100


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    total_symbols = con.execute("SELECT COUNT(DISTINCT symbol) FROM prices").fetchone()[0]

    df = pd.read_csv(OUT / "24_random_windows.csv")
    elig, members, labels = [], [], []
    for _, r in df.iterrows():
        st = coverage_stats("NIFTY500", r["start"], base_dir=ROOT)
        e, m = int(st["eligible_symbols"]), int(st["members"])
        elig.append(e); members.append(m)
        labels.append("VALID" if e >= min_pit_eligible(m) else "DATA_INSUFFICIENT")
    con.close()
    df["eligible_symbols"] = elig
    df["pit_members"] = members
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
        "rule": "VALID iff eligible PIT members >= max(10, members//2), capped at 100",
        "universe": "NIFTY500 point-in-time membership",
        "total_db_symbols": int(total_symbols),
        "all_200": block(df),
        "valid_only": block(df[df.label == "VALID"]),
        "data_insufficient_only": block(df[df.label == "DATA_INSUFFICIENT"]),
        "modern_2016_plus_all": block(df[df.start >= "2016-01-01"]),
        "modern_2016_plus_valid": block(df[(df.start >= "2016-01-01") & (df.label == "VALID")]),
        "counts": {k: int(v) for k, v in df.label.value_counts().items()},
        "note": "maxdd is the C-kernel DAILY intra-period drawdown; cagr uses sessions/252.",
    }
    (OUT / "33b_random_window_quality.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
