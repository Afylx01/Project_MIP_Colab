# PIT Universe Rebuild — NIFTY 500

**Date:** 2026-10-25 · **Verdict:** `PIT_VERIFIED` · **Certificate:** `certificates/PIT_UNIVERSE_CERTIFICATE.json`

## 1. What was wrong

The v2.4.2 "point-in-time" table came from niftyhistory.in. Verified against **17 exact NSE
constituent files recovered from the Internet Archive**, it scores:

| Metric | Value |
|---|---:|
| Mean Jaccard vs NSE anchors | **0.709** |
| Mean recall vs NSE anchors | **0.816** |
| Worst anchor | 2018-10-04: Jaccard **0.455**, recall 0.626 |

At the 2018 anchors only 63% of the real NIFTY 500 was present, and 55% of the table's names were
wrong. The failure mode was visible directly: `VAML`, `VEDPOWER`, `DUMMYHEG`, `HEGAM`, `VISL`,
`VOGL` — 2025-26 demerger/dummy scrips — appeared in **all 50 snapshots back to 2016-01-18**.
The walk-back had leaked the current seed backwards. No backtest computed on that table is valid.

| Anchor | Old Jaccard | Old recall |
|---|---:|---:|
| 2018-10-04 | 0.455 | 0.626 |
| 2019-02-01 | 0.457 | 0.628 |
| 2020-07-25 | 0.472 | 0.642 |
| 2022-05-04 | 0.527 | 0.690 |
| 2022-10-09 | 0.541 | 0.702 |
| 2023-04-04 | 0.567 | 0.724 |
| 2024-02-07 | 0.605 | 0.754 |
| 2024-02-26 | 0.605 | 0.754 |
| 2025-06-16 | 0.770 | 0.869 |
| 2025-08-15 | 0.773 | 0.872 |
| 2025-08-21 | 0.773 | 0.872 |
| 2026-01-07 | 0.812 | 0.896 |
| 2026-05-02 | 0.889 | 0.938 |
| 2026-08-27 | 0.903 | 0.950 |
| 2026-09-21 | 0.905 | 0.950 |
| 2026-10-09 | 1.000 | 1.000 |
| 2026-10-22 | 1.000 | 1.000 |

## 2. What replaces it

`scripts/build_pit_membership.py`:

1. **17 anchors** — NSE-published `ind_nifty500list.csv` captures from niftyindices.com,
   nseindia.com and archives.nseindia.com (2018-10-04 → 2026-10-22), stored with sha256 in
   `data/pit_constituents/anchors/manifest.json`. On an anchor date the anchor wins.
2. **86 press-release events** (2014-02-28 → 2026-05-12) from the CC BY 4.0
   `aditya-jha/nse-historical-membership` parser, vendored as
   `data/pit_constituents/nifty500_events.csv`.
3. **Dated ticker renames** applied while walking, so `IDFCBANK → IDFCFIRSTB`,
   `CADILAHC → ZYDUSLIFE`, `MINDTREE/LTI → LTM` etc. do not create phantom members.
4. **Forward walk with snapping** — between anchors, membership is advanced from the previous
   anchor through events; every later anchor resets the state, so drift cannot accumulate past an
   anchor. Dates before 2018-10-04 fall back to the interval table (tier C).
5. **DUMMY\* scrips excluded** from the tradable universe.

Result: **180 snapshots (2016-01-18 → 2026-10-22), 90,355 rows, 83,028 mapped to a price series
(91.9%)**, stored in `data/pit_constituents/nifty500_snapshots.csv` and loaded into
`universe.db` as `index_membership` (1,218 intervals, 948 unique symbols) + `pit_manifest`.

## 3. Verification (all gates PASS)

| Gate | Result |
|---|---|
| STRUCTURE | True — 180 snapshots, no duplicates, cardinality inside 488-512 |
| ANCHORS_EXACT | True — every NSE anchor reproduced name-for-name |
| CROSS_SOURCE | True — interval table vs anchors, mean Jaccard 0.955 |
| LISTING_CONSTRAINT | True — no mapped member before its first price bar |
| COVERAGE | True — 91.9% of member-dates map to a DB series |
| CHURN | True — worst month-over-month change 68 names |
| IMPROVEMENT | True — old table 0.709 / 0.816 vs anchors; new table 1.000 at anchors |

Cross-source detail (interval table vs NSE anchor):

| Anchor | Jaccard | Anchor-only | Interval-only |
|---|---:|---:|---:|
| 2018-10-04 | 0.909 | 23 | 25 |
| 2019-02-01 | 0.912 | 22 | 24 |
| 2020-07-25 | 0.927 | 17 | 21 |
| 2022-05-04 | 0.946 | 14 | 14 |
| 2022-10-09 | 0.949 | 13 | 13 |
| 2023-04-04 | 0.953 | 11 | 13 |
| 2024-02-07 | 0.971 | 7 | 8 |
| 2024-02-26 | 0.971 | 7 | 8 |
| 2025-06-16 | 0.986 | 5 | 2 |
| 2025-08-15 | 0.990 | 3 | 2 |
| 2025-08-21 | 0.990 | 3 | 2 |
| 2026-01-07 | 0.994 | 2 | 1 |
| 2026-05-02 | 0.992 | 4 | 0 |
| 2026-08-27 | 0.992 | 2 | 2 |
| 2026-09-21 | 0.990 | 3 | 2 |
| 2026-10-09 | 0.885 | 31 | 30 |
| 2026-10-22 | 0.885 | 31 | 30 |

The 2018-19 gap (~0.91) is the interval table's missing pre-2020 exclusion events (e.g. ABB was a
2018 member per NSE, excluded before 2020 and re-included 2020-06-26 with the exclusion missing
from the PR parse). Anchors are used directly on their own dates, so this affects only dates
between anchors.

## 4. Database + certificate

`data/universe.db` now contains:

```
index_membership(index_name, symbol, db_symbol, valid_from, valid_to, source)
pit_manifest(key, value)
```

| Item | Value |
|---|---|
| DB sha256 | `26df1c076d02728c6d72ffaf41e0b8c2c559ea7cff001612eea073e1bb383090` |
| DB bytes | 352,485,376 |
| prices rows | 2,170,608 |
| max date | 2026-10-19 |
| integrity_check | ok |
| PIT intervals | 1,218 |

`certificates/PRODUCTION_READINESS_CERTIFICATE.json` is regenerated from the live tree and is now
the contract future runs check against (`scripts/verify_production_readiness.py` reads the expected
sha/rows/date from it instead of hard-coded literals). It records
`verdict = PIT_VERIFIED` and `governance_mode = PIT_ANCHOR_VERIFIED__PRICE_DATA_PARTIAL`, because
the price series still has **1,325 open discontinuities** (see the deep-scan report). The
certificate deliberately does not claim blanket production readiness.

## 5. Coverage impact

| Date | Mapped / members | Before |
|---|---:|---:|
| 2017-01-01 | 428 | 375 |
| 2018-01-01 | **446** | 377 |
| 2018-12-28 | 453 | ~380 |
| 2024-01-01 | 470 | 453 |
| 2026-01-01 | 496 | 493 |

Tradable PIT breadth at the canonical 2018 start rises from **356 to 439 eligible symbols** (+23%).

## 6. Reproduce

```bash
python3 scripts/build_pit_membership.py
python3 scripts/verify_pit_membership.py --strict
MIP_ALLOW_PROD_MUTATION=1 python3 scripts/load_pit_into_db.py --write
python3 scripts/refresh_data_certificate.py
```

Anchors are committed, so the rebuild is offline and deterministic; `anchors/manifest.json` pins
each capture URL and sha256.


## 6b. Test evidence

`python3 -m pytest -q -p no:cacheprovider` after the rebuild:

**635 passed, 5 skipped, 0 failed in 1,349.18 s (22:29)** — exit 0. Recorded in
`reports/test_evidence.json` and embedded in the production certificate. New regression tests
(`tests/test_pit_source_integrity.py`) fail if an anchor is lost, a DUMMY scrip leaks in,
cardinality drifts outside 488-512, or the PIT certificate is not green. Two stale expectations
were corrected: ADANIENT is not a 2018 member (NSE excluded it 2018-04-02, re-included 2020-09-25)
and the 2017 mapped count moved from 375 to 428.

## 7. Still open

- Price-series discontinuities were reduced from 1,325 to **248** on 2026-10-25 (431 spikes flattened,
  227 vendor scale shifts back-adjusted on 2016-01-04 and 2020-09-15). The 248 remaining are 177 rows of
  the 2026-09-01 resume block plus 71 isolated corporate actions; see `reports/VERIFIED_STRATEGY_2026-10-25.md`.
- Corporate-action registry covers 6 events; CCAVENUE (+840% on 2026-10-19) and HEG (-62.6%) unexplained.
- Pre-2018-10-04 membership has no NSE anchor (tier C).
- The canonical backtest **has now been re-run** on the rebuilt membership (17.24% CAGR / 0.62 Sharpe,
  see `reports/VERIFIED_STRATEGY_2026-10-25.md`); the survivorship control is the remaining follow-up.
