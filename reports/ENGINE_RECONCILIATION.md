# Engine reconciliation — PIT membership

Generated 2026-10-24T13:21:30Z. Period 2018-01-01..2026-08-31; costs 15 bps friction + 5 bps slippage.

## Policy

- Historical index universe: **NIFTY500 point-in-time membership**, resolved per rebalance date.
- A 2016-01-01 start is refused: no snapshot exists on or before it. The canonical window starts in 2018, the first year with ≥70% tradable coverage (356 eligible of 377 mapped). 2017 is runnable (305 eligible, verified) but is outside the pre-registered window.
- Live scanner: latest constituents (the only component allowed to use them).
- Breadth gate: at least **100** eligible PIT members (scaled down for small indices).

## Canonical baselines (NIFTY500 PIT, 2018–2026)

- **Production backtest** (Python): CAGR **22.94%**, Sharpe 0.82, MaxDD -23.66%, 492 trades.
- **Strategy-engine baseline** (C99 kernel, config D): CAGR **23.70%**, Sharpe 0.80, daily MaxDD 26.44%, 484 trades.

## Every published (engine, universe, config)

| Engine | Universe | Config | Method | CAGR % | Sharpe | MaxDD % | DD basis | Trades | Status |
|---|---|---|---|---:|---:|---:|---|---:|---|
| C99 kernel | NIFTY500 (PIT) | D | continuous | 23.70 | 0.80 | 26.44 | daily intra-period | 484 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | D | monthly-sampled | 23.19 | 0.83 | -24.40 | monthly rebalance NAV | 484 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | A | continuous | 25.52 | 0.90 | 27.86 | daily intra-period | 534 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | A | monthly-sampled | 24.97 | 0.92 | -27.10 | monthly rebalance NAV | 534 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | B | continuous | 26.29 | 0.96 | 27.34 | daily intra-period | 702 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | C | continuous | 24.61 | 0.79 | 31.16 | daily intra-period | 512 | REPRODUCED |
| C99 kernel | NIFTY500 (PIT) | E | continuous | 24.50 | 0.89 | 26.59 | daily intra-period | 1045 | REPRODUCED |
| C99 kernel | ALL (reference) | D | continuous | 24.70 | 0.80 | 30.38 | daily intra-period | 551 | REPRODUCED |
| C99 kernel | NIFTY750 | D | — | — | — | — | — | — | REFUSED |
| Python LightweightBacktester | NIFTY750 | D | — | — | — | — | — | — | REFUSED |
| Python LightweightBacktester | ALL (full cross-section, legacy) | D | continuous | 29.59 | 1.06 | -23.65 | monthly | 703 | RETIRED_LEGACY_NON_PIT |
| C99 kernel | NIFTY750 (current-list, historical) | D | monthly | 29.28 | 0.96 | -34.63 | monthly | 652 | RETIRED_SURVIVORSHIP_BIAS |
| Python LightweightBacktester | NIFTY500 (current 2026 list, 2016 start) | D | continuous | 30.01 | 1.13 | -20.47 | monthly | 604 | RETIRED_SURVIVORSHIP_BIAS |
| Python LightweightBacktester | NIFTY500 (PIT) | D | continuous | 22.94 | 0.82 | -23.66 | monthly | 492 | REPRODUCED |
| Python LightweightBacktester | NIFTY500 (current 2026 list, biased control) | D | continuous | 25.75 | 0.93 | -20.96 | monthly | 495 | BIASED_CONTROL |

`RETIRED_LEGACY_NON_PIT` rows are old numbers that are not reproducible under the PIT contract (the 04b row starts 2016-01-01, before the first snapshot, and holds the full ALL cross-section rather than an index). `RETIRED_SURVIVORSHIP_BIAS` rows applied a 2026 constituent list backwards. Both are listed so they are explicitly retired rather than silently deleted, and neither is part of the canonical contract. `REFUSED` rows are named indices or windows with no PIT table/breadth.

## Continuous vs monthly-sampled (same config, same PIT universe)

| Quantity | Continuous | Monthly-sampled | Mechanism |
|---|---:|---:|---|
| CAGR | 23.70% | 23.19% | identical ending equity; sessions/252 vs months/12 |
| Ending equity | ₹5,988,673 | ₹5,988,673 | identical path |
| Trades | 484 | 484 | identical selection |
| Sharpe | 0.80 | 0.83 (T+1 0.82) | INCOMPLETE: kernel internal series not exposed |
| MaxDD | 26.44% daily | -24.40% monthly | daily intra-period vs monthly sampling |

## Stress windows — PIT breadth-gated

| Window | PIT members | Eligible | Raw DB 252-bar (at window end) | Label | Strategy total (config A) | Benchmark total | Aligned | Headline? |
|---|---:|---:|---:|---|---:|---:|---|---|
| gfc_2008 | 0 | 0 | 94/1083 (8.68%) | **DATA_INSUFFICIENT** | —% | —% | False | False |
| euro_2011 | 0 | 0 | 106/1083 (9.79%) | **DATA_INSUFFICIENT** | —% | —% | False | False |
| midcap_2018 | 377 | 356 | 757/1083 (69.9%) | **VALID** | -19.68% | -5.78% | True | True |
| covid_2020 | 401 | 378 | 801/1083 (73.96%) | **VALID** | -3.4% | -22.46% | True | True |
| full_2018_2026 | 377 | 356 | 1006/1083 (92.89%) | **VALID** | 577.5% | 142.08% | True | True |

Stress-window strategy totals and benchmark totals use the recommended **config A** monthly validation harness (`21_strategy_validation.json`, same PIT membership and effective windows); the canonical config-D production result is in the baseline section above and is not a stress-window total.

Under-covered windows are refused by the engine, not merely labelled. The raw DB column is the independent check: at 2008-12-31 only 94 of 1,083 symbols (8.7%) have 252 bars; at 2011-12-31, 106 (9.8%). The shortfall is the documented data artifact, so 2008/2011 are DATA_INSUFFICIENT and no headline claim depends on them.

## Survivorship / look-ahead control

Same production engine, config D, dates and costs; only membership differs.

| Run | Universe | CAGR | Sharpe | MaxDD | Trades |
|---|---|---:|---:|---:|---:|
| PIT (canonical) | 553 symbols, per-rebalance | 22.94% | 0.82 | -23.66% | 492 |
| Current 2026 list (biased control) | 487 symbols | 25.75% | 0.93 | -20.96% | 495 |

**Current-list look-ahead overstatement: +2.81 pp CAGR.**

## Provenance

| Item | Value |
|---|---|
| Primary membership source | niftyhistory.in full Nifty500 snapshots |
| Secondary cross-check | aditya-jha/nse-historical-membership (CC BY 4.0) |
| Snapshot coverage | 2016-01-18 onward; canonical 2018-2026 |
| Resolution | Per rebalance date; dead names included while members |
| Verification | reports/PIT_MEMBERSHIP_VERIFICATION.md |

## Reproduction

```bash
python3 scripts/build_pit_constituents.py
python3 reports/analysis_evidence/canonical_backtest.py
python3 reports/analysis_evidence/validate_candidates.py
python3 reports/analysis_evidence/summarize_candidates.py
python3 reports/analysis_evidence/reconcile_engines.py
python3 reports/analysis_evidence/label_random_windows.py
```
