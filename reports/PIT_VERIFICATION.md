# PIT Universe Verification — NIFTY 500

**Verdict: PASS** · 2026-10-25T04:43:20.428064+00:00

- Table: `data/pit_constituents/nifty500_snapshots.csv` · sha256 `5368c7822755ce81…`
- Snapshots: **180** (2016-01-18 → 2026-10-22)
- NSE anchors: **17** · cross-source Jaccard **0.955**
- Price mapping coverage: **91.9%**

| Gate | Result | Detail |
|---|---|---|
| STRUCTURE | PASS | `{"duplicates": 0, "cardinality_violations": {}, "snapshots": 180, "min": "2016-01-18", "max": "2026-10-22"}` |
| ANCHORS_EXACT | PASS | `{"per_anchor": {"2018-10-04": {"anchor_members": 501, "table_members": 501, "exact": true, "missing": [], "extra": []}, "2019-02-01": {"anchor_members": 501, "t` |
| CROSS_SOURCE | PASS | `{"mean_jaccard": 0.9553, "per_anchor": {"2018-10-04": {"jaccard": 0.9086, "anchor_only": 23, "interval_only": 25}, "2019-02-01": {"jaccard": 0.9122, "anchor_onl` |
| LISTING_CONSTRAINT | PASS | `{"violations": [], "count": 0}` |
| COVERAGE | PASS | `{"mapped": 83028, "rows": 90355, "ratio": 0.9189}` |
| CHURN | PASS | `{"worst_date": "2024-03-31", "worst_change": 68}` |
| IMPROVEMENT | PASS | `{"old_table_vs_anchors": {"anchors_compared": 17, "old_mean_jaccard": 0.709, "old_mean_recall": 0.8157, "detail": [{"date": "2018-10-04", "jaccard": 0.4549, "re` |

Old table at anchors: Jaccard 0.709, recall 0.816 → new table 1.000 (anchors are exact).
