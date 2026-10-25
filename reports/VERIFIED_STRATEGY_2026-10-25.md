# Verified Strategy Results — NIFTY 500 PIT + repaired prices (v2.5.0)

**Date:** 2026-10-25 · **Database:** `universe.db` sha `9d2c74b1…` · **PIT:** 17 NSE anchors · **Prices:** vendor artifacts repaired
**Window:** 2018-01-01 → 2026-08-31 · **Costs:** 15 bps friction + 5 bps slippage

## 0. What changed since the first pass

| Layer | Before | After |
|---|---|---|
| Membership | niftyhistory table (0.71 Jaccard) | 17 exact NSE anchors + press-release walk |
| Prices | 1,325 unexplained discontinuities | **248** (177 = 2026-09 resume block, 71 isolated CAs) |
| Repair | — | 431 single-row spikes flattened, 227 vendor scale shifts back-adjusted on 2016-01-04, 2020-09-15 |
| Engine parity | scanner had an anomaly gate, backtester did not | both engines now block a symbol for 252 sessions after an unexplained >35% move (20,685 member-days blocked in the C cube) |

Repair ledger: `data/price_repairs.json`; every edit is also recorded in the `price_repairs` table of
`universe.db`. Raw pre-repair state: `data/universe.db.pre_repair_20261025`.

## 1. Canonical strategy (unchanged logic)

| Metric | Python | C99 kernel |
|---|---:|---:|
| CAGR | **20.21%** | 19.89% |
| NIFTY 500 | 11.08% | 11.08% |
| Excess | **+9.13 pp** | +8.81 pp |
| Sharpe | **0.76** (90% CI 0.20–1.41) | 0.71 |
| Sortino | 1.04 | — |
| MaxDD (monthly / daily) | -27.22% / -29.00% | 28.76% |
| Trades | 495 | 473 |
| Win rate | 43.4% | — |

> History of this number: 22.94% (retracted membership) → 17.24% (verified membership, raw prices)
> → **20.21%** (verified membership + repaired prices + break firewall).

## 2. Survivorship / look-ahead control

| Universe | CAGR | Sharpe | MaxDD | Trades |
|---|---:|---:|---:|---:|
| Verified PIT membership | **20.21%** | 0.76 | -27.22% | 495 |
| Today's 2026 list applied backwards | 25.76% | 0.98 | −20.43% | 487 |

**Look-ahead overstatement: +5.55 pp CAGR** on clean data (was +8.51 pp before the price repair).
Artifact: `reports/verified/current_list_control.json`.

## 3. Full grid

2,400 configurations (top_n × lookback × EMA × retrace × sector cap), monthly, same filters/costs,
C99 kernel with the break firewall: **2,400 runs in 8.3 s**.

| Statistic | Value |
|---|---:|
| Sharpe mean / std / min / max | 0.485 / 0.180 / -0.193 / 0.932 |
| Configs with Sharpe > 0.9 | 5 |
| Canonical | 19.89% / 0.706 |
| Best | 27.50% / 0.932 |

After the repair the optimum moved to **short lookbacks (126–189) with small books (top_n = 10)** —
the opposite of the pre-repair grid, where 315-day lookbacks dominated. The pre-repair optimum was
driven by the very discontinuities now removed, which is itself evidence the repair mattered.

## 4. Top-5 settings (optimisation candidates)

| Setting (top_n / lookback / EMA / retrace / sector) | Python CAGR | Sharpe | MaxDD | Trades | Sharpe 90% CI | Window wins | Median rank |
|---|---:|---:|---:|---:|---|---:|---:|
| 10 / 189 / 250 / 0.80 / 2 | 27.51% | 0.95 | -25.37% | 200 | 0.39–1.61 | 4/24 | 2.0 |
| 10 / 189 / 200 / 0.80 / 2 | 27.53% | 0.95 | -25.37% | 200 | 0.38–1.62 | 0/24 | 2.2 |
| 10 / 126 / 250 / 0.75 / 1 | 28.27% | 1.01 | -25.34% | 269 | 0.46–1.61 | 3/24 | 4.0 |
| 10 / 126 / 250 / 0.70 / 1 | 28.85% | 1.02 | -25.33% | 267 | 0.48–1.66 | 1/24 | 5.0 |
| 10 / 126 / 150 / 0.70 / 1 | 28.02% | 0.99 | -28.59% | 268 | 0.43–1.61 | 1/24 | 5.0 |

Reference — canonical: 20.21% / 0.76 / -27.22% / 495 trades.
Most robust: `10 / 189 / 250 / 0.80 / 2` (median window rank 2.0; median window CAGR 41.6%,
median excess vs NIFTY 500 +26.1 pp, worst window −5.9%).

## 5. Cross-engine validation (same parameters)

| Config | Python CAGR | C CAGR | Δ | Python Sharpe | C Sharpe |
|---|---:|---:|---:|---:|---:|
| 10/189/250/0.80/2 | 27.51% | 27.41% | −0.10 | 0.95 | 0.916 |
| 10/126/250/0.70/1 | 28.85% | 27.50% | −1.35 | 1.02 | 0.932 |
| 10/189/200/0.80/2 | 27.53% | 26.88% | −0.65 | 0.95 | 0.889 |
| 10/126/150/0.70/1 | 28.02% | 27.21% | −0.81 | 0.99 | 0.914 |
| 10/126/250/0.75/1 | 28.27% | 26.67% | −1.60 | 1.01 | 0.903 |
| canonical 20/252/200/0.80/2 | 20.21% | 19.89% | −0.32 | 0.76 | 0.706 |

Two independent implementations agree within 1.6 pp CAGR; the Python engine is systematically a
little higher (exit/execution accounting on halted names).

## 6. Out-of-window robustness

24 random windows (2–5 years, 2018+, seed 20261025), benchmark NIFTY 500:

| Config | Median CAGR | Worst window | Median excess | Beats benchmark | Median Sharpe |
|---|---:|---:|---:|---:|---:|
| canonical | 29.46% | −6.17% | +14.72 pp | 23/24 (96%) | 1.13 |
| 10/189/250/0.80/2 | 41.58% | −5.88% | +26.06 pp | 23/24 (96%) | 1.31 |

Schedule sensitivity (canonical): monthly 19.89%; weekly remains destructive (≈3% CAGR with >70%
drawdown), quarterly/half-yearly sit in between — monthly is the production cadence.

## 7. Statistical fact-check

- Bootstrap (5,000 resamples of 103 monthly returns): canonical Sharpe 90% CI **0.20–1.41**, P(Sharpe>0)=**98.7%**, CAGR CI 8.8%–33.0%.
- Top-1: Sharpe CI **0.39–1.61**, P>0=99.7%.
- Multiple testing: with 2,400 trials the expected maximum Sharpe under the null is **0.629**. Top-1's 0.932 → Deflated Sharpe **0.81**; canonical's 0.76 → 0.49.
- Reading: the canonical edge survives the data repair and is positive in 23/24 windows, but the
  best grid variant still falls short of the 0.95 DSR bar. It stays a research candidate.

## 8. Verdict

1. PIT membership is true and verified; price artifacts are repaired and every edit is auditable.
2. The canonical strategy survives: **+9.13 pp** over the NIFTY 500 with a 0.76 Sharpe on clean data.
3. The optimisation candidates roughly **+7–9 pp** over the canonical, but their Deflated Sharpe
   (0.81) does not clear 0.95 — no production change is justified yet.
4. Next: forward paper validation (2026-10 → 2027-06) and a second independent price source for the
   remaining 71 isolated corporate-action breaks.

## 9. Reproduce

```bash
python3 scripts/repair_price_series.py --dry-run      # plan (431 spikes, 227 shifts)
MIP_ALLOW_PROD_MUTATION=1 python3 scripts/repair_price_series.py --apply
python3 scripts/run_verified_campaign.py              # 2,400-run grid + schedules + windows
python3 scripts/rank_verified_results.py              # bootstrap + DSR + top-5
```
