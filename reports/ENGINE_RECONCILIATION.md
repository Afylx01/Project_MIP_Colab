# Engine reconciliation — 2026-10-23

Generated 2026-10-23T20:27:10Z. Period 2016-01-01..2026-08-31; costs 15 bps friction + 5 bps slippage.

## Canonical baselines (both NIFTY500)

- **Production backtest** (Python, canonical): CAGR **30.01%**, Sharpe 1.13, MaxDD -20.47%, 604 trades
- **Strategy-engine baseline** (C99 kernel, config D): CAGR **27.39%**, Sharpe 0.91, daily MaxDD 38.32%, 595 trades
- Both universes are NIFTY500 current constituents; both carry `survivorship_bias_risk=True`.

## Every published (engine, universe, config)

| Engine | Universe | Config | Method | CAGR % | Sharpe | MaxDD % | DD basis | Trades | Status |
|---|---|---|---|---:|---:|---:|---|---:|---|
| C99 kernel | NIFTY500 | D | continuous | 27.39 | 0.91 | 38.32 | daily intra-period | 595 | REPRODUCED |
| C99 kernel | NIFTY500 | D | monthly-sampled | 26.81 | 0.98 | -20.69 | monthly rebalance NAV | 595 | REPRODUCED |
| C99 kernel | NIFTY500 | A | continuous | 33.12 | 1.17 | 26.83 | daily intra-period | 674 | REPRODUCED |
| C99 kernel | NIFTY500 | A | monthly-sampled | 32.4 | 1.2 | -21.36 | monthly rebalance NAV | 674 | REPRODUCED |
| C99 kernel | NIFTY500 | B | continuous | 33.18 | 1.22 | 30.07 | daily intra-period | 881 | REPRODUCED |
| C99 kernel | NIFTY500 | C | continuous | 37.69 | 1.05 | 32.37 | daily intra-period | 673 | REPRODUCED |
| C99 kernel | NIFTY500 | E | continuous | 32.85 | 0.95 | 30.43 | daily intra-period | 1340 | REPRODUCED |
| C99 kernel | NIFTY750 | D | continuous | 28.13 | 0.92 | 34.63 | daily intra-period | 639 | REPRODUCED |
| C99 kernel | ALL | D | continuous | 27.0 | 0.89 | 37.95 | daily intra-period | 689 | REPRODUCED |
| C99 kernel | SURVIVORS | D | continuous | 28.51 | 0.95 | 35.63 | daily intra-period | 674 | REPRODUCED |
| Python LightweightBacktester | NIFTY500 | D | continuous | 30.01 | 1.13 | -20.47 | monthly | 604 | REPRODUCED |
| Python LightweightBacktester | ALL | D | continuous | 29.59 | 1.06 | -23.65 | monthly | 703 | REPRODUCED |

## §5.5 vs §9 D — same config, different numbers

Both rows are NIFTY500, config D (LB252/EMA200/top20/buf40/cap2/ATR), 2016-01-01→2026-08-31.

| Quantity | §5.5 (continuous kernel) | §9 D (monthly-sampled) | Mechanism |
|---|---:|---:|---|
| CAGR | 27.39% | 26.81% | same ending equity; sessions/252 vs months/12 |
| Ending equity | ₹12,354,160 | ₹12,354,160 | identical path |
| Trades | 595 | 595 | identical selection |
| Sharpe | 0.91 | 0.98 (T+1: 0.93) | **INCOMPLETE**: kernel internal series not exposed; T+1 explains most of the gap |
| MaxDD | 38.32% daily | -20.69% monthly | daily intra-period vs monthly sampling |

The previously published §9 D value **28.69%** was equal-weight: the harness passed integer code `0`, and `bridge.py:431` treated any non-string code as equal-weight. The corrected ATR monthly value is **26.81%**; the continuous ATR value is **27.39%**. The CAGR residual is annualization; the drawdown residual is daily-vs-monthly sampling. The Sharpe sub-gap is **INCOMPLETE**, not attributed.

## Stress windows — labelled, not assumed

| Window | Sessions | 252-bar coverage | Label | Strategy total | Benchmark total | Aligned | Headline? |
|---|---:|---:|---|---:|---:|---|---|
| gfc_2008 | 246 | 14.77% (74/501) | **DATA_INSUFFICIENT** | -6.67% | -57.13% | True | False |
| euro_2011 | 246 | 16.17% (81/501) | **DATA_INSUFFICIENT** | -17.67% | -27.19% | True | False |
| midcap_2018 | 246 | 68.66% (344/501) | **VALID** | -2.88% | -3.38% | True | True |
| covid_2020 | 100 | 72.26% (362/501) | **VALID** | -3.75% | -20.77% | True | True |
| full_2016_2026 | 2637 | 94.01% (471/501) | **VALID** | 1850.5% | 269.91% | True | True |

The 2008 and 2011 windows fail the coverage rule (≈15% and ≈16% of today's NIFTY500 constituents have the required 252-bar history). Any drawdown claim that depends on them is retracted from headline status and retained only as a labelled data-insufficiency note.

**2008 denominator:** 76 DB symbols have any 2008 bar (7.0% of the 1,083-symbol database), but only 74 have the required 252-bar history and are current NIFTY500 members (14.8% of 501). The "~75 symbols / 7%" caveat is therefore correct against the full database; against the declared universe it is 14.8%. Both fail the 50% rule.

## Survivorship bias — one number from a real run

Same engine, same config D, same dates. ALL symbols: **1083**; still quoting after 2026-08-31: **1033** (50 dead names).

- CAGR ALL: **27.00%**
- CAGR survivors only: **28.51%**
- Survivorship overstatement: **1.51 pp CAGR**
- NIFTY500-vs-ALL (index membership + breadth, not survivorship alone): **0.39 pp**

## Reproduction

```bash
python3 reports/analysis_evidence/validate_candidates.py   # 21, aligned windows
python3 reports/analysis_evidence/summarize_candidates.py  # 22, continuous engine
python3 reports/analysis_evidence/reconcile_engines.py     # 33 + this report
```
