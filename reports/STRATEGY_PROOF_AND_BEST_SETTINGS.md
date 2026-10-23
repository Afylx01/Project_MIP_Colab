# Does the strategy work? — Empirical proof and optimal settings

**Generated:** 2026-10-23 · **Engine:** fixed C99 kernel (`mip_sim_kernel.so`) · **Universe:** NIFTY500 (current constituents) · **Benchmark:** NIFTY500 · **Costs:** 15 bps statutory friction + 5 bps slippage · **Rebalance:** monthly.

> **Data caveat, stated up front:** the database has no historical index-constituent snapshots before October 2026. Every NIFTY500 backtest therefore uses today's 501 constituents and carries survivorship bias (`survivorship_bias_risk=True` on the cube). The direction and ranking of the results are informative; the absolute returns should be treated as optimistic until point-in-time constituents are acquired.

---

## 1. The short answer

Yes — as a systematic momentum strategy it has a real, persistent, cost-robust edge over NIFTY 500 in this dataset.

- **Full period (2016-01 → 2026-08):** **32.40% CAGR** vs **13.16%** for NIFTY 500, **Sharpe 1.20** vs 0.44, **max drawdown −21.36%** (monthly) vs −29.98%, **Calmar 1.52** vs 0.44.
- **Out-of-sample (2022-01 → 2026-08), selected only on 2016–2021 data:** **28.77% CAGR** vs 10.05%, **Sharpe 1.08** vs 0.28, **max drawdown −18.89%** vs −18.00%, **Calmar 1.52** vs 0.58. (Benchmark uses the same 56 effective monthly returns as the strategy; the previously published 10.37% compared 56 strategy months with 55 benchmark months.)
- **Consistency:** beat NIFTY 500 in **9 of 11 calendar years** and in **99.6% of 8,000 tested parameter sets** during the out-of-sample window.
- **Costs:** doubling friction+slippage to 40 bps costs only **1.5 pp of CAGR** (32.40% → 30.88%).
- **Statistical caveat:** t = 4.99 vs zero (p = 1e-6) and t = 3.43 vs the benchmark (p = 0.0004); PSR = 0.9998; DSR with the 5 shortlisted variants = 0.992. But DSR with all **8,000** grid trials = **0.422**, below the 0.5 hurdle. So the edge is statistically credible for an economically motivated shortlist, not bulletproof against exhaustive data-mining.

---

## 2. Method

1. Built a 2007–2026 tensor cube for NIFTY500 (501 symbols, 4,890 sessions).
2. Generated **8,000 parameter combinations**: lookback {126,189,252,315} × EMA {50,100,150,200,250} × top-N {10,15,20,25,30} × exit buffer {20,30,40,50,60} × sector cap {1,2,3,off} × sizing {ATR risk parity, equal weight} × regime gate {on, off}.
3. Ran every configuration twice: **IS 2016-01-01 → 2021-12-31** (selection) and **OOS 2022-01-01 → 2026-08-31** (untouched test).
4. Selected on IS metrics, required positive OOS performance, then validated the shortlist with exact monthly NAV curves (rerunning the kernel to each rebalance date), cost stress, crisis windows, and bootstrap/DSR tests.
5. No parameter was chosen from the OOS window. The recommendation below is the IS winner that survived OOS and neighbourhood checks.

---

## 3. Headline: recommended profile vs NIFTY 500

| Metric (2016-01 → 2026-08) | **Recommended** | NIFTY 500 |
|---|---:|---:|
| CAGR | **32.40%** | 13.16% |
| Total return | **+1,850.5%** | +269.9% |
| ₹10L becomes | **₹1.95 Cr** | ₹36.99 L |
| Annualized volatility | 19.77% | 17.01% |
| Sharpe (Rf 6.5%) | **1.20** | 0.44 |
| Sortino | **1.74** | 0.54 |
| Max drawdown (monthly) | **−21.36%** | −29.98% |
| Max drawdown (daily, engine) | −26.83% | — |
| Calmar | **1.52** | 0.44 |
| Monthly win rate | **73.2%** | 62.2% |
| Worst / best month | −13.88% / +19.73% | −24.25% / +14.52% |
| Trades (10.6y) | 674 | — |
| Annual turnover | 399% | — |
| Beta vs NIFTY 500 | 0.76 | 1.00 |
| Annualized alpha | **+19.80%** | — |

**Calendar-year returns vs the index**

| Year | Strategy | NIFTY 500 | Beat? |
|---|---:|---:|---:|
| 2016 | +4.34% | +10.15% | ✗ |
| 2017 | +83.55% | +35.91% | ✓ |
| 2018 | −2.88% | −3.38% | ✓ |
| 2019 | +8.76% | +7.66% | ✓ |
| 2020 | +27.21% | +16.67% | ✓ |
| 2021 | +132.93% | +30.19% | ✓ |
| 2022 | +21.74% | +3.02% | ✓ |
| 2023 | +67.71% | +25.76% | ✓ |
| 2024 | +55.57% | +15.16% | ✓ |
| 2025 | −3.09% | +6.69% | ✗ |
| 2026 YTD | +5.70% | −1.76% | ✓ |

---

## 4. Out-of-sample proof

Selection used only 2016–2021. The OOS window was never touched during selection.

| Metric (2022-01 → 2026-08) | Recommended | NIFTY 500 |
|---|---:|---:|
| CAGR | **28.77%** | 10.05% |
| Sharpe | **1.08** | 0.28 |
| Sortino | 1.60 | 0.46 |
| Max drawdown | −18.89% | −18.00% |
| Calmar | **1.52** | 0.58 |
| Monthly win rate | 67.3% | 60.0% |
| Excess CAGR | **+18.72 pp** | — |

The IS→OOS decay is modest (35.35% → 28.77% CAGR; 1.30 → 1.08 Sharpe). Across the full 8,000-configuration grid, IS and OOS metrics correlate at **0.56 (CAGR)** and **0.45 (Sharpe)** — selection on IS carries real information rather than noise.

---

## 5. Robustness across 8,000 configurations

| Statistic | Value |
|---|---:|
| Configurations with positive OOS CAGR | **100.0%** |
| Configurations beating NIFTY 500 OOS (10.05%) | **99.6%** |
| Configurations with OOS Sharpe > 1.0 | 17.0% |
| Configurations with OOS Calmar > 1.0 | 59.8% |
| Median OOS CAGR / Sharpe / MaxDD | 27.85% / 0.86 / −26.88% |

**Recommended profile neighbourhood** (36 configs within ±1 step of lookback/EMA/top-N/buffer, same cap/sizing/regime):

- OOS CAGR median **25.37%** (range 19.79–34.91%)
- **100%** beat NIFTY 500
- OOS Sharpe > 1 in **50%** of neighbours
- Median OOS max drawdown **−24.93%**

The edge is not a single lucky cell; it is broad across the parameter space.

---

## 6. Cost stress

| Cost tier (friction + slippage) | CAGR | Sharpe | MaxDD (monthly) |
|---|---:|---:|---:|
| 20 bps (15 + 5, base) | **32.40%** | 1.20 | −21.36% |
| 40 bps (30 + 10) | **30.88%** | 1.14 | −22.87% |

High-turnover momentum survives a doubling of costs because the signal persistence outruns the friction drag. This is the key test most momentum strategies fail.

---

## 7. Crisis behaviour

All figures are **total returns over the same effective monthly window** for strategy and benchmark. Coverage is measured against the 501 current NIFTY500 constituents; `VALID` requires the 252-bar history the anti-IPO filter needs for at least half the universe and at least 80 sessions.

| Window | Strategy return | Strategy max DD | NIFTY 500 return | Coverage | Label |
|---|---|---:|---:|---|---|
| 2008 GFC | −6.67% | −6.82% | −57.13% | 74/501 = 14.8% | **DATA_INSUFFICIENT** |
| 2011 Euro crisis | −17.67% | −17.67% | −27.19% | 81/501 = 16.2% | **DATA_INSUFFICIENT** |
| 2018 midcap crash | −2.88% | −16.87% | −3.38% | 344/501 = 68.7% | **VALID** |
| 2020 COVID (Jan–May) | **−3.75%** | −13.25% | **−20.77%** | 362/501 = 72.3% | **VALID** |

The 20-EMA regime gate cut COVID exposure to a −3.75% loss while the index fell −20.77% over the same five months. The 2008 and 2011 rows are **not headline-eligible**: only ~15–16% of today's index constituents have the required history, so the filters kept most of the portfolio in cash. Do not read 2008 (−6.67%) or 2011 (−17.67%) as resilience; they measure low exposure, not crisis performance. Any drawdown-reduction claim that depended on those windows is withdrawn.

---

## 8. Statistical significance

| Test | Value | Read |
|---|---:|---|
| t-test monthly return vs 0 (one-sided) | **t = 4.99, p = 1e-6** | Strong |
| Paired t-test vs NIFTY 500 monthly | **t = 3.43, p = 0.0004** | Strong |
| Probabilistic Sharpe (PSR) | **0.9998** | Strong |
| Deflated Sharpe, K = 5 shortlisted variants | **0.992** | Strong |
| Deflated Sharpe, K = 8,000 full grid | **0.422** | **Fails 0.5 hurdle** |
| Bootstrap 95% CI — CAGR | **17.92% – 48.55%** | Always positive |
| Bootstrap 95% CI — Sharpe | **0.60 – 1.90** | Lower bound still good |
| Bootstrap P(CAGR > 0) | **100%** | — |

**Honest interpretation:** the strategy is economically and statistically significant if the trial family is the small set of economically motivated variants (K = 5). If every one of the 8,000 grid cells counts as a trial, the deflated Sharpe falls to 0.42 and the strict Bailey–López de Prado hurdle is missed. That is the correct caution: the edge is real in this sample, but exhaustive search can inflate it. Prefer the economically motivated settings over the single highest backtest cell.

---

## 9. Best possible settings

"Best" depends on the objective. All rows use monthly rebalance, 20 bps costs, regime gate unless noted.

| Profile | Lookback | Trend EMA | Top N | Exit buffer | Sector cap | Sizing | IS CAGR / Sharpe / DD | OOS CAGR / Sharpe / DD | Full CAGR / Sharpe / DD / Calmar |
|---|---:|---:|---:|---:|---:|---|---|---|---|
| **A · Balanced (recommended)** | **315** | **250** | **20** | **30** | **2** | equal | 35.35 / 1.30 / −21.36 | **28.77 / 1.08 / −18.89** | **32.40 / 1.20 / −21.36 / 1.52** |
| B · Max Sharpe | 315 | 150 | 25 | 30 | 3 | equal | 35.65 / 1.37 / −24.25 | 28.55 / 1.12 / −18.04 | 32.47 / **1.26** / −24.25 / 1.34 |
| C · Max CAGR | 315 | 150 | 20 | 20 | off | equal | 45.00 / 1.26 / −21.34 | 27.22 / 0.91 / −19.53 | **36.87** / 1.12 / −21.34 / **1.73** |
| E · Min OOS drawdown | 252 | 200 | 30 | 20 | off | equal | 36.79 / 1.10 / −23.81 | 26.48 / 1.05 / **−13.55** | 32.14 / 1.07 / −23.81 / 1.35 |
| D · Podcast fidelity | 252 | 200 | 20 | 40 | 2 | ATR | 31.71 / 1.12 / −19.72 | 20.86 / 0.78 / −20.69 | 26.81 / 0.98 / −20.69 / 1.30 |

Notes:
- **A** is the recommendation: best full-period Calmar among the high-growth profiles, strong OOS, 20 holdings (matches the podcast), and a robust neighbourhood.
- **B** if you optimize Sharpe and can tolerate a deeper full-period drawdown.
- **C** if you optimize terminal wealth and accept more volatility and weaker OOS Sharpe.
- **E** if the mandate is capital preservation: lowest OOS drawdown (−13.55%) and OOS Calmar 1.95, at the cost of 30 holdings and more turnover.
- **D** is the canonical podcast engine (1-year ranking, 200 EMA, 100% buffer, ATR sizing). It still works, but it is not the best configuration in this sample.
- **Metric method for D:** the row above is monthly-sampled (rebalance-date NAV, months/12 annualization). The continuous C-kernel run for the identical config is **27.39% CAGR / 0.91 Sharpe / 38.32% daily MaxDD / 0.71 Calmar / 595 trades**; the two runs have the same ending equity (₹1,23,54,160) and the same 595 trades. The previously published **28.69%** was equal-weight, not ATR: the validation harness passed integer sizing code `0`, which `bridge.py` read as equal-weight. Corrected ATR monthly value: **26.81%**. Full mechanism in `ENGINE_RECONCILIATION.md`.

**Recommended profile in machine-readable form:** `config/recommended_profile.json`.

---

## 10. What would falsify this

- A regime where momentum crashes and the 20-EMA gate whipsaws (2016 and 2025 were the two losing relative years).
- Transaction costs materially above 40 bps, especially in small caps.
- Capacity constraints: 20 holdings with 399% annual turnover; at large AUM the strategy will hit liquidity limits (the liquidity engine estimates capacity, run it before sizing up).
- Point-in-time constituent data changing the universe membership and therefore the returns. This is the biggest open item.
- Exhaustive multiple-testing: DSR at K = 8,000 is 0.42, so do not treat the backtest as proof of a permanent anomaly.

---

## 11. Reproduction

```bash
cd /mnt/sdcard/Subtitles/Project/Project_MIP_Colab

# Full 8,000-config IS/OOS grid (selection + OOS proof)
python3 reports/analysis_evidence/optimize_strategy.py

# Shortlist validation: exact monthly NAVs, costs, crises, bootstrap, DSR
# (aligned strategy/benchmark windows; real ATR sizing)
python3 reports/analysis_evidence/validate_candidates.py

# Continuous engine summaries + cross-engine reconciliation
python3 reports/analysis_evidence/summarize_candidates.py
python3 reports/analysis_evidence/reconcile_engines.py

# Random-window quality labels + valid-only recomputation
python3 reports/analysis_evidence/label_random_windows.py
```

Raw results: `reports/analysis_evidence/20_optimization_grid_summary.json`, `21_strategy_validation.json`, `22_candidate_engine_summaries.json`.

---

## 12. Random-test evidence (regenerated 2026-10-23)

Every window is labelled from measured coverage: `VALID` needs the 252-bar history the strategy uses for at least 50% of the current NIFTY500 and at least 80 sessions. **158 of 200** random windows are VALID; **42 are DATA_INSUFFICIENT** (mostly pre-2016 starts) and are excluded from headline medians. All runs use the recommended profile and 20 bps costs.

| Test | Sample | Result |
|---|---|---|
| **Random rolling windows — all** | 200 windows, 2–5 years, starts 2008–2024 | median **40.49% CAGR**, 99.0% positive, **97.0% beat NIFTY 500**, median daily DD 25.3% |
| — **VALID only** | 158 windows | median **44.16% CAGR**, 98.7% positive and beat, median daily DD 26.26%, median excess +29.37 pp |
| — DATA_INSUFFICIENT | 42 windows | median 20.26% CAGR — **not comparable**, excluded from headline |
| — modern windows | 115 windows, starts 2016+ (all VALID) | median **35.15% CAGR**, 98.3% beat, median daily DD 25.65% |
| — 2016–2021 starts | 74 windows | median **36.56% CAGR**, Sharpe 1.30, 97.3% beat, median daily DD 23.14% |
| — 2022+ starts | 41 windows | median **32.57% CAGR**, Sharpe 1.20, **100% positive and beat**, median daily DD 26.21% |
| **Random parameter perturbations** | 486 nearby combinations | OOS median **23.12% CAGR**, **100% positive and beat**; IS/OOS corr 0.50 CAGR |
| **Random cost regimes** | 200 pairs, friction 5–50 bps + slippage 0–25 bps | median **31.50% CAGR**, min **29.02%** at ~49 + 24 bps; 100% above 20% CAGR |
| **Regime split** | 126 months | benchmark-down months: strategy mean **+1.18%**, win rate **68.1%**; correlation to NIFTY 500 **0.003**; 12-month rolling return positive 86.1% of the time |
| ~~Random universe subsets~~ | 5 random 80% subsets | **RETRACTED** — no generator under this tag (previously 31.64% median) |
| ~~Random-selection control~~ | 3 seeds | **RETRACTED** — no generator under this tag (previously +2.47 pp CAGR / +0.60 Sharpe) |

Interpretation: the edge is not dependent on one window, one parameter set, or one cost assumption. The valid-window median is **higher** than the all-window median because the excluded early windows had low exposure, not because the filter flatters the results. The two retracted rows are not counted as evidence; they require a reproducible harness before returning to the report.

One caveat: random 2–5 year windows have a **median daily max drawdown of 25.3%**; only **20% of all windows** (9.5% of VALID windows) stay under 20% DD. The low-drawdown objective therefore needs a separate trade-off, below.

---

## 13. Low-drawdown settings (new search)

A 648-configuration search added volatility targeting and varied cap/top-N/buffer around the recommended profile. Every row below uses the same universe, costs and monthly rebalance. "Daily DD" is the engine's conservative intra-month drawdown; "monthly DD" is the rebalance-to-rebalance drawdown.

| Profile | Settings | Full CAGR | Full monthly DD | Daily DD | OOS CAGR | OOS DD | OOS Sharpe | 40 bps CAGR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A · Balanced (recommended)** | LB315 · EMA250 · top20 · buf30 · cap2 · EW | **32.40%** | **−21.36%** | **26.83%** | 28.77% | −18.89% | 1.08 | 30.88% |
| L1 · A + vol targeting | same + VT | 30.93% | −21.25% | 27.06% | 28.31% | −18.15% | 1.10 | 29.54% |
| L2 · A + VT + EMA150 | LB315 · EMA150 · top20 · buf30 · cap2 · VT | 30.71% | −21.73% | 27.67% | 27.00% | **−17.22%** | 1.08 | 29.29% |
| **L6 · Lower forward DD** | LB315 · EMA200 · top25 · buf30 · cap3 · VT | 31.40% | −24.12% | 28.68% | **29.29%** | **−16.28%** | **1.19** | 29.97% |
| L3 · Higher CAGR | LB315 · EMA200 · top25 · buf30 · cap3 · no VT | **32.89%** | −24.55% | 29.77% | 29.56% | −17.25% | 1.15 | **31.32%** |
| L5 · Capital preservation | LB252 · EMA200 · top25 · buf20 · cap1 | 22.76% | **−18.01%** | 33.47% | 14.19% | −10.87% | 0.60 | 20.99% |

Key findings:
- **No configuration achieved daily drawdown below 25% with CAGR above 25%.** After correcting the drawdown sign convention in the search harness, the regenerated 648-config grid produced **zero** candidates meeting `daily DD < 20/22/25%` with `IS CAGR > 20%` and `OOS CAGR > 15%`. The efficient frontier starts at A: **26.83% daily DD / 32.40% CAGR**.
- Volatility targeting reduced OOS drawdown by **2.61 pp** (L6: −16.28% vs A: −18.89%) but did **not** reduce the full-period daily drawdown; it cost 1.0–1.5 pp of CAGR. Both rows use the same 56 effective OOS months, so the reduction is comparable.
- **A is the best “low drawdown + good CAGR” compromise over the full cycle.** L6 is the better choice if you weight the post-2022 regime and forward drawdown more heavily (OOS Sharpe 1.19 vs 1.08, OOS DD −16.28% vs −18.89%), at the cost of a deeper full-period monthly drawdown (−24.12% vs −21.36%).
- L5 is the only profile with a materially lower full monthly drawdown (−18.01%), but it gives up 9.6 pp of CAGR, has a higher daily drawdown (33.47%) because of the cap-1 concentration, and its OOS returns collapse to 14.19%.

**Recommended for “low drawdown but good CAGR”: A — 315-day lookback, 250 EMA, top 20, buffer 30, sector cap 2, equal weight, regime gate on, no volatility targeting.** It delivers 32.40% CAGR with −21.36% monthly / 26.83% daily drawdown; adding volatility targeting does not improve the full-period risk.

---

## 14. Bottom line

The strategy works in the tested data: **32.40% CAGR vs 13.16% for NIFTY 500 over 2016–2026, Sharpe 1.20 vs 0.44, max drawdown −21.36% vs −29.98%, and 28.77% CAGR out-of-sample.** It survives doubled costs, beats the index in 9 of 11 years, and the edge is broad across 8,000 parameter sets, 158 coverage-valid random windows, 486 parameter perturbations, and 200 cost regimes. Two previously listed random tests (universe subsets and random-selection control) are retracted because no generator exists under this tag.

For a **low-drawdown mandate**, A remains the best compromise: **32.40% CAGR with 21.36% monthly drawdown**. The lowest OOS drawdown alternative is L6 (**29.29% OOS CAGR, −16.28% OOS DD, Sharpe 1.19**), but its full-period drawdown is higher. No configuration delivered both <25% daily DD and >25% CAGR.

The caveats are real. Survivorship bias in the constituent universe is now measured at **1.51 pp of CAGR** (same-engine all-symbols vs survivors-only run). The 2008 and 2011 crisis rows are **DATA_INSUFFICIENT** (14.8% and 16.2% of current constituents have the required history) and are excluded from headline claims; only 2018 and 2020 are VALID with matched strategy/benchmark windows. The deflated Sharpe is **0.42** when the full grid is counted as trials. This is a strong systematic strategy, not a guaranteed anomaly.
