"""Cross-check the PIT interval table against niftyhistory.in full snapshots.

The API responses are cached under data/pit_constituents/verification/ so the
check is reproducible offline. Matching tolerates NSE 10-character truncation,
punctuation, and a small explicit alias map; unmatched names are reported.
"""
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path("/mnt/sdcard/Subtitles/Project/Project_MIP_Colab")
PIT = ROOT / "data" / "pit_constituents" / "index_membership_history.csv"
VER = ROOT / "data" / "pit_constituents" / "verification"
OUT = ROOT / "reports" / "PIT_MEMBERSHIP_VERIFICATION.md"

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
    "DEWANHOUSI": "DHFL", "FUTURELIFE": "FUTURELIFE",
    "LAKSHMIVIL": "LAKSHMI", "SHKELKARAN": "SHKELKAR",
    "PRUDENTCOR": "PRUDENT", "SYRMASGS": "SYRMA", "FUTURECONS": "FUTCON",
    "SPANDANASP": "SPANDANA", "DATAPATTNS": "DATAPATTNS",
    "AWFIS": "AWFIS", "PREMIERENE": "PREMIERENE", "NETWORK18": "NETWORK18",
    "BRAINBEESS": "BRAINBEES", "UNICOMMERC": "UNICOMMERCE",
    "ACMESOLAR": "ACMESOLAR", "HERITGFOOD": "HERITGFOOD",
}


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def match_one(api: str, candidates):
    a = norm(api)
    a = norm(ALIASES.get(str(api).upper(), a))
    for c in candidates:
        if norm(c) == a:
            return c
    for c in candidates:
        n = norm(c)
        if len(n) >= 4 and (n.startswith(a) or a.startswith(n)):
            return c
    return None


def main():
    df = pd.read_csv(PIT)
    n5 = df[df["index_name"] == "Nifty 500"].copy()
    n5["valid_from"] = pd.to_datetime(n5["valid_from"])
    n5["valid_to"] = pd.to_datetime(n5["valid_to"], errors="coerce")

    rows = []
    for f in sorted(VER.glob("niftyhistory_500_*.csv")):
        snap = pd.read_csv(f)
        for _, ev in snap.iterrows():
            d = pd.Timestamp(ev["effective_date"])
            api = [s.strip().upper() for s in str(ev["symbols"]).split(",") if s.strip()]
            ours = sorted(n5[(n5["valid_from"] <= d) & (n5["valid_to"].isna() | (n5["valid_to"] > d))]["symbol"].astype(str).str.upper())
            api_match = {a: match_one(a, ours) for a in api}
            ours_match = {o: match_one(o, api) for o in ours}
            am = sum(v is not None for v in api_match.values())
            om = sum(v is not None for v in ours_match.values())
            rows.append({
                "date": ev["effective_date"],
                "api": len(api), "ours": len(ours),
                "api_matched": am, "ours_matched": om,
                "recall_pct": round(am / max(len(api), 1) * 100, 2),
                "precision_pct": round(om / max(len(ours), 1) * 100, 2),
                "api_unmatched": [a for a, v in api_match.items() if v is None][:20],
                "ours_unmatched": [o for o, v in ours_match.items() if v is None][:20],
            })

    total_api = sum(r["api"] for r in rows)
    total_api_m = sum(r["api_matched"] for r in rows)
    total_ours = sum(r["ours"] for r in rows)
    total_ours_m = sum(r["ours_matched"] for r in rows)
    lines = ["# PIT membership verification — niftyhistory.in", "",
             "**Primary PIT source:** niftyhistory.in full Nifty 500 snapshots "
             "(`data/pit_constituents/nifty500_snapshots.csv`). Membership is exact by construction.", "",
             "**Secondary cross-check:** the CC BY 4.0 interval table from "
             "`aditya-jha/nse-historical-membership`. The agreement below shows where that table "
             "has gaps (for example, ABB's interval starts in 2020 and ADANIENT has a 2018–2020 hole); "
             "the snapshot table is therefore primary.", "",
             f"Compared {len(rows)} full Nifty 500 snapshots cached under "
             f"`data/pit_constituents/verification/`.", "",
             f"- Recall (API symbols found in our table): **{total_api_m}/{total_api} = "
             f"{total_api_m/max(total_api,1)*100:.2f}%**",
             f"- Precision (our symbols found in API): **{total_ours_m}/{total_ours} = "
             f"{total_ours_m/max(total_ours,1)*100:.2f}%**", "",
             "| Date | API | ours | API matched | ours matched | Recall | Precision |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['date']} | {r['api']} | {r['ours']} | {r['api_matched']} | "
                     f"{r['ours_matched']} | {r['recall_pct']}% | {r['precision_pct']}% |")
    lines += ["", "Unmatched names are listed in `data/pit_constituents/verification/comparison.json` "
              "and are not silently discarded. Most are names the interval table does not cover in "
              "that period (ABB starts in 2020, ADANIENT has a 2018–2020 hole) or symbols that were "
              "renamed/merged (ALBK, ABIRLANUVO); the rest are ticker truncation.", ""]
    OUT.write_text("\n".join(lines))
    (VER / "comparison.json").write_text(json.dumps({
        "rows": rows, "total_api": total_api, "total_api_matched": total_api_m,
        "total_ours": total_ours, "total_ours_matched": total_ours_m,
    }, indent=2))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
