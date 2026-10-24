# Does the strategy work? — Point-in-time NIFTY500 evidence

**Generated:** 2026-10-24 · **Engine:** fixed C99 kernel (`mip_sim_kernel.so`) · **Universe:** NIFTY500 **point-in-time membership** · **Benchmark:** NIFTY500 · **Costs:** 15 bps statutory friction + 5 bps slippage · **Rebalance:** monthly · **Period:** 2018-01-01 → 2026-08-31.

> **Universe correction (2026-10-24):** the previous version applied the 2026 NIFTY500 list to 2016–2026. That is survivorship/look-ahead biased and is retired. This version resolves membership **on each rebalance date** from full NIFTY500 snapshots (niftyhistory.in, cross-checked against the CC BY 4.0 `nse-historical-membership` interval table). A **2016-01-01 start is refused** (no snapshot on or before it). The canonical window starts in 2018, the first year with ≥70% tradable coverage; 2017 is runnable (305 eligible, verified) but is outside the pre-registered window. The live scanner still uses the latest constituents.
>
> **Data completeness caveat:** 377 of 501 members in 2018 map to a DB price series and 356 have the required 252 bars (453 mapped / 434 eligible by 2024; 496 mapped by 2026). The remainder have no usable price history and cannot be traded. This is a data limitation, not a membership-selection bias. The canonical period starts in 2018 because earlier years fail the breadth gate.

---

## 1. The short answer

The strategy has a measurable edge over NIFTY 500 on point-in-time membership, but it is smaller than the old biased backtest implied.

- **Full period (2018-01 → 2026-08):** **24.97% CAGR** vs **10.85%** for NIFTY 500, **Sharpe 0.92** vs 0.31, **max drawdown −27.10%** (monthly) vs −31.85%, **Calmar 0.92** vs 0.34.
- **Out-of-sample (2022-01 → 2026-08), selected only on 2018–2021 data:** **25.83% CAGR** vs 10.20%, **Sharpe 1.00** vs 0.30, **max drawdown −19.62%** vs −18.02%, **Calmar 1.32** vs 0.57.
- **Consistency:** beat NIFTY 500 in **6 of 9 calendar years** (5 of 8 full years), and **98.7% of 8,000 tested parameter sets** beat the benchmark in the OOS window.
- **Costs:** doubling friction+slippage to 40 bps costs **1.42 pp of CAGR** (24.97% → 23.55%).
- **Statistical caveat:** t = 3.69 vs zero (p = 0.00018) and t = 2.37 vs the benchmark (p = 0.0098); PSR = 0.9937; DSR with the 5 shortlisted variants = 0.904. But DSR with all **8,000** grid trials = **0.095**, far below the 0.5 hurdle. The shortlist edge is significant; exhaustive-search robustness is not.

---

## 2. Method

1. Built the tensor cube on **NIFTY500 point-in-time membership** from 50 snapshots covering 2016-01-18 → 2026-09-30 (membership constant between events).
2. Every rebalance filters candidates to the members on that date; a holding removed from the index is exited at the next rebalance (`INDEX_REMOVAL`).
3. Generated **8,000 parameter combinations**: lookback {126,189,252,315} × EMA {50,100,150,200,250} × top-N {10,15,20,25,30} × exit buffer {20,30,40,50,60} × sector cap {1,2,3,off} × sizing {ATR risk parity, equal weight} × regime gate {on, off}.
4. Ran every configuration twice: **IS 2018-01-01 → 2021-12-31** (selection) and **OOS 2022-01-01 → 2026-08-31** (untouched test).
5. Validated the shortlist with exact monthly NAV curves, cost stress, crisis windows, and bootstrap/DSR tests. Membership is point-in-time throughout.

---

## 3. Headline: recommended profile vs NIFTY 500

| Metric (2018-01 → 2026-08) | **Recommended (A)** | NIFTY 500 |
|---|---:|---:|
| CAGR | **24.97%** | 10.85% |
| Total return | **+577.50%** | +142.08% |
| ₹10L becomes | **₹67.75 L** | ₹24.21 L |
| Annualized volatility | 18.53% | 17.65% |
| Sharpe (Rf 6.5%) | **0.92** | 0.31 |
| Sortino | **1.21** | 0.37 |
| Max drawdown (monthly) | **−27.10%** | −31.85% |
| Max drawdown (daily, engine) | −27.86% | — |
| Calmar | **0.92** | 0.34 |
| Monthly win rate | 71.8% | 62.1% |
| Worst / best month | −15.66% / +17.39% | −26.33% / +12.91% |
| Trades (8.6y) | 534 | — |
| Annual turnover | 475.8% | — |
| Beta vs NIFTY 500 | 0.72 | 1.00 |
| Annualized alpha | **+15.70%** | — |

**Calendar-year returns vs the index**

| Year | Strategy | NIFTY 500 | Beat? |
|---|---:|---:|---:|
| 2018 | −19.68% | −3.38% | ✗ |
| 2019 | −0.59% | +7.66% | ✗ |
| 2020 | +34.32% | +16.67% | ✓ |
| 2021 | +112.08% | +30.19% | ✓ |
| 2022 | +29.24% | +3.02% | ✓ |
| 2023 | +46.85% | +25.76% | ✓ |
| 2024 | +57.68% | +15.16% | ✓ |
| 2025 | −6.44% | +6.69% | ✗ |
| 2026 YTD | +6.38% | −7.67% | ✓ |

---

## 4. Out-of-sample proof

Selection used only 2018–2021. The OOS window was never touched during selection.

| Metric (2022-01 → 2026-08) | Recommended | NIFTY 500 |
|---|---:|---:|
| CAGR | **25.83%** | 10.20% |
| Sharpe | **1.00** | 0.30 |
| Sortino | 1.35 | 0.49 |
| Max drawdown | −19.62% | −18.02% |
| Calmar | **1.32** | 0.57 |
| Monthly win rate | 71.9% | 61.4% |
| Excess CAGR | **+15.63 pp** | — |

The IS→OOS change is **+1.92 pp CAGR** (23.91% → 25.83%) and **+0.17 Sharpe** (0.83 → 1.00). Across the full 8,000-configuration grid, IS and OOS metrics correlate only at **0.183 (CAGR)** and **0.157 (Sharpe)** — low, so selection on IS carries limited information. That is a caution, not a proof of persistence.

---

## 5. Robustness across 8,000 configurations

| Statistic | Value |
|---|---:|
| Configurations with positive OOS CAGR | **100.0%** |
| Configurations beating NIFTY 500 OOS (10.85%) | **98.7%** |
| Configurations with OOS Sharpe > 1.0 | 7.4% |
| Configurations with OOS Calmar > 1.0 | 28.0% |
| Median OOS CAGR / Sharpe / MaxDD | 23.13% / 0.74 / −27.86% |

**Recommended profile neighbourhood** (54 configs within ±1 step of lookback/EMA/top-N/buffer, same cap/sizing/regime):

- OOS CAGR median **26.85%**
- **100%** positive OOS
- OOS Calmar median **1.074**

The edge is broad across the parameter space, but the low IS/OOS correlation means the single best IS cell should not be trusted; prefer the economically motivated profile.

---

## 6. Cost stress

| Cost tier (friction + slippage) | CAGR | Sharpe | MaxDD (monthly) |
|---|---:|---:|---:|
| 20 bps (15 + 5, base) | **24.97%** | 0.92 | −27.10% |
| 40 bps (30 + 10) | **23.55%** | 0.86 | — |

High-turnover momentum survives a doubling of costs, but the drag is material: 1.42 pp of CAGR. At ~49 + 24 bps the worst random cost run still returned 21.60%.

---

## 7. Crisis behaviour

All figures are **total returns over the same effective monthly window** for strategy and benchmark. PIT membership is used throughout.

| Window | Strategy return | Strategy max DD | NIFTY 500 return | PIT members / eligible | Label |
|---|---|---:|---:|---|---|
| 2008 GFC | — | — | — | 0 / 0 | **DATA_INSUFFICIENT** (no PIT snapshot; 94/1,083 DB symbols have 252 bars = 8.7%) |
| 2011 Euro crisis | — | — | — | 0 / 0 | **DATA_INSUFFICIENT** (no PIT snapshot; 106/1,083 = 9.8%) |
| 2018 midcap crash | −19.68% | −20.51% | −5.78% | 377 / 356 | **VALID** |
| 2020 COVID (Jan–May) | **−3.40%** | −13.00% | **−22.46%** | 401 / 378 | **VALID** |

The 20-EMA regime gate cut COVID exposure to a −3.40% loss while the index fell −22.46% over the same five months. The strategy **underperformed in the 2018 midcap crash** (−19.68% vs −5.78%); do not read it as a hedge in every drawdown. 2008 and 2011 are **DATA_INSUFFICIENT**: no PIT snapshot predates 2016, and the raw DB has only 94 (8.7%) / 106 (9.8%) symbols with 252 bars by those year-ends (74 of today's 501 NIFTY500 members, 14.8%, for 2008). The engine refuses them; no headline or drawdown-reduction claim depends on them.

---

## 8. Statistical significance

| Test | Value | Read |
|---|---|---|
| t-test monthly return vs 0 (one-sided) | **t = 3.69, p = 0.00018** | Strong |
| Paired t-test vs NIFTY 500 monthly | **t = 2.37, p = 0.0098** | Significant at 1% |
| Probabilistic Sharpe (PSR) | **0.9937** | Strong |
| Deflated Sharpe, K = 5 shortlisted variants | **0.904** | Good |
| Deflated Sharpe, K = 8,000 full grid | **0.095** | **Fails 0.5 hurdle** |
| Bootstrap 95% CI — CAGR | **9.10% – 42.08%** | Positive lower bound |
| Bootstrap 95% CI — Sharpe | **0.21 – 1.72** | Wide |
| Bootstrap P(CAGR > 0) | **99.93%** | — |

**Honest interpretation:** the strategy is statistically distinguishable from the benchmark for the economically motivated shortlist (K = 5, DSR 0.90). If every one of the 8,000 grid cells counts as a trial, the deflated Sharpe collapses to 0.095 and the strict Bailey–López de Prado hurdle is missed. Do not treat the backtest as proof of a permanent anomaly.

---

## 9. Best possible settings

"Best" depends on the objective. All rows use monthly rebalance, 20 bps costs, PIT membership, regime gate unless noted.

| Profile | Lookback | Trend EMA | Top N | Exit buffer | Sector cap | Sizing | IS CAGR / Sharpe / DD | OOS CAGR / Sharpe / DD | Full CAGR / Sharpe / DD / Calmar |
|---|---:|---:|---:|---:|---:|---|---|---|---|
| **A · Balanced (recommended)** | **315** | **250** | **20** | **30** | **2** | equal | 23.91 / 0.83 / −27.10 | **25.83 / 1.00 / −19.62** | **24.97 / 0.92 / −27.10 / 0.92** |
| B · Max Sharpe | 315 | 150 | 25 | 30 | 3 | equal | 23.80 / 0.83 / −26.53 | 27.29 / **1.11** / −16.53 | 25.72 / **0.98** / −26.53 / **0.97** |
| C · Max CAGR (shortlist) | 315 | 150 | 20 | 20 | off | equal | 23.31 / 0.79 / −29.55 | 24.70 / 0.83 / −21.42 | 24.08 / 0.82 / −29.55 / 0.81 |
| E · Min OOS drawdown | 252 | 200 | 30 | 20 | off | equal | 21.93 / 0.79 / −25.28 | 25.65 / 1.03 / **−15.07** | 23.98 / 0.92 / −25.28 / 0.95 |
| D · Podcast fidelity | 252 | 200 | 20 | 40 | 2 | ATR | 28.26 / 0.90 / −24.40 | 19.24 / 0.76 / −21.50 | 23.19 / 0.83 / −24.40 / 0.95 |
| **R · Grid-robust** | 315 | 200 | 20 | 30 | 3 | ATR | 28.20 / 0.84 / −22.41 | **30.85 / 1.16 / −24.53** | not shortlisted |

Notes:
- **A** is the recommendation: best full-period Calmar among the high-growth profiles, strong OOS, 20 holdings (matches the podcast), and a robust neighbourhood. It is not the highest CAGR.
- **B** if you optimize Sharpe and can tolerate a slightly deeper full-period drawdown.
- **C** is no longer the max-CAGR cell once membership is point-in-time; it is retained as the shortlist's growth variant.
- **E** if the mandate is capital preservation: lowest OOS drawdown (−15.07%) and OOS Calmar 1.70.
- **D** is the canonical podcast engine. Its monthly-sampled row is above; the continuous C-kernel run is **23.70% CAGR / 0.80 Sharpe / 26.44% daily MaxDD / 0.90 Calmar / 484 trades**.
- **R** is the grid's `best_robust_min_calmar` selection (LB315/EMA200/top20/buf30/cap3/ATR). It was selected on IS and had the strongest OOS Calmar (1.26). It is not the recommended profile because its cap-3/ATR combination has higher turnover and a deeper OOS drawdown than A.

**Metric method:** table values are monthly-sampled (rebalance-date NAV, months/12 annualization), with strategy and benchmark on the same T+1 period ends. The continuous C-kernel row for the same config is reported in `reports/ENGINE_RECONCILIATION.md`.

**Recommended profile in machine-readable form:** `config/recommended_profile.json`.

---

## 10. What would falsify this

- A regime where momentum crashes and the 20-EMA gate whipsaws (2018, 2019, and 2025 were losing absolute years).
- Transaction costs materially above 40 bps, especially in small caps.
- Capacity constraints: 20 holdings with 476% annual turnover; at large AUM the strategy will hit liquidity limits.
- Point-in-time membership changing the universe: this version already uses it; the residual risk is missing price history for ~24% of 2018 members.
- Exhaustive multiple-testing: DSR at K = 8,000 is 0.095, so do not treat the backtest as proof of a permanent anomaly.

---

## 11. Reproduction

```bash
cd /mnt/sdcard/Subtitles/Project/Project_MIP_Colab

# Normalize the niftyhistory snapshots into the PIT table
python3 scripts/build_pit_constituents.py
python3 scripts/verify_pit_against_niftyhistory.py

# Full 8,000-config IS/OOS grid (PIT membership)
python3 reports/analysis_evidence/optimize_strategy.py

# Shortlist validation: exact monthly NAVs, costs, crises, bootstrap, DSR
python3 reports/analysis_evidence/validate_candidates.py

# Continuous engine summaries + cross-engine reconciliation
python3 reports/analysis_evidence/summarize_candidates.py
python3 reports/analysis_evidence/reconcile_engines.py

# Random-window quality labels + valid-only recomputation
python3 reports/analysis_evidence/label_random_windows.py
```

Raw results: `reports/analysis_evidence/20_optimization_grid_summary.json`, `21_strategy_validation.json`, `22_candidate_engine_summaries.json`, `23_optimization_grid.csv`, `33_reconciliation.json`, `33b_random_window_quality.json`, `34_python_canonical.json`, `35_current_list_control.json`.

---

## 12. Random-test evidence (PIT)

All windows start in 2018 or later; every one passes the PIT breadth gate.

| Test | Sample | Result |
|---|---|---|
| **Random rolling windows** | 200 windows, 2–5 years, starts 2018–2024 | median **36.71% CAGR**, 98.0% positive, **97.0% beat NIFTY 500**, median excess +23.01 pp, median daily DD 25.45% |
| **Random parameter perturbations** | 486 nearby combinations | OOS median **21.58% CAGR**, **100% positive**, **99.6% beat**; IS/OOS corr 0.154 CAGR |
| **Random cost regimes** | 200 pairs, friction 5–50 bps + slippage 0–25 bps | median **24.00% CAGR**, min **21.60%** at ~49 + 24 bps; 100% above 20% |
| **Regime split** | 102 months | benchmark-down months: strategy mean **+0.43%**, win rate **65.0%**; correlation to NIFTY 500 **0.062**; 12-month rolling return positive 79.1% of the time |

Interpretation: the edge is not dependent on one window, one parameter set, or one cost assumption. It is weaker than the biased universe suggested: median random-window CAGR is 36.71%, not 40%+, and the regime correlation is 0.062, not 0.003.

One caveat: random 2–5 year windows have a **median daily max drawdown of 25.45%**; only **3.5%** stay under 20% DD. The low-drawdown objective therefore needs a separate trade-off, below.

---

## 13. Low-drawdown settings

A 648-configuration search varied vol targeting, cap, top-N and buffer around the recommended profile. Every row uses PIT membership, monthly rebalance, 20 bps costs. "Daily DD" is the engine's conservative intra-month drawdown; "monthly DD" is the rebalance-to-rebalance drawdown.

| Profile | Settings | Full CAGR | Full monthly DD | Daily DD | OOS CAGR | OOS DD | OOS Sharpe | 40 bps CAGR |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A · Balanced (recommended)** | LB315 · EMA250 · top20 · buf30 · cap2 · EW | **24.97%** | **−27.10%** | 27.86% | 25.83% | −19.62% | 1.00 | 23.55% |
| L1 · A + vol targeting | same + VT | 22.52% | −27.94% | 28.68% | 25.31% | −18.80% | 1.03 | 21.19% |
| L2 · A + VT + EMA150 | LB315 · EMA150 · top20 · buf30 · cap2 · VT | 21.41% | −25.06% | 28.93% | 23.26% | −18.10% | 0.96 | 20.05% |
| **L3 · Higher CAGR** | LB315 · EMA200 · top25 · buf30 · cap3 · no VT | **26.75%** | −25.21% | 29.30% | **28.47%** | −15.55% | 1.15 | **25.32%** |
| L5 · Capital preservation | LB252 · EMA200 · top25 · buf20 · cap1 | 17.69% | **−22.09%** | 30.88% | 14.32% | −13.37% | 0.62 | 16.09% |
| L6 · Lower OOS DD | LB315 · EMA200 · top25 · buf30 · cap3 · VT | 24.66% | −25.38% | 29.69% | 28.25% | **−14.68%** | **1.19** | 23.33% |

Key findings:
- **No configuration achieved daily drawdown below 20% or 22%.** The 648-config grid produced zero candidates meeting `daily DD < 20/22%` with `IS CAGR > 20%` and `OOS CAGR > 15%`; one config met `< 25%` (LB315/EMA250/top20/buf30/cap3 ATR, IS 26.72% / OOS 31.20%).
- Volatility targeting reduced OOS drawdown by **3.07 pp** (L6: −14.68% vs A: −19.62%) and improved OOS Sharpe (1.19 vs 1.00), at a cost of 0.31 pp of full-period CAGR and a **shallower** full-period monthly drawdown (−25.38% vs −27.10%).
- **A is the best “low drawdown + good CAGR” compromise over the full cycle.** L6 is the better choice if you weight the post-2022 regime and forward drawdown more heavily.
- L5 is the only profile with a materially lower full monthly drawdown (−22.09%), but it gives up 7.28 pp of CAGR and its OOS returns collapse to 14.32%.

**Recommended for “low drawdown but good CAGR”: A — 315-day lookback, 250 EMA, top 20, buffer 30, sector cap 2, equal weight, regime gate on, no volatility targeting.** It delivers 24.97% CAGR with −27.10% monthly / 27.86% daily drawdown; adding volatility targeting improves forward drawdown but not the full-period risk.

---

## 14. Bottom line

The strategy works in the tested data: **24.97% CAGR vs 10.85% for NIFTY 500 over 2018–2026, Sharpe 0.92 vs 0.31, max drawdown −27.10% vs −31.85%, and 25.83% CAGR out-of-sample.** It survives doubled costs and beats the index in 6 of 9 calendar years. The edge is broad across 8,000 parameter sets, 200 random windows, 486 parameter perturbations, and 200 cost regimes.

For a **low-drawdown mandate**, A remains the best compromise: **24.97% CAGR with 27.10% monthly drawdown**. L6 is the best forward-drawdown alternative (**28.25% OOS CAGR, −14.68% OOS DD, Sharpe 1.19**), but its full-period monthly drawdown is higher. No configuration delivered both <20% daily DD and >25% CAGR.

The caveats are real and material. Membership is now point-in-time (2016-01-01 refused; canonical starts 2018 with 356/501 tradable members), which removes the old survivorship/look-ahead bias but also removes the inflated returns. The measured control — same production engine, config and dates on today's 2026 NIFTY500 list — overstates CAGR by **+2.81 pp** (25.75% vs 22.94%), which is the current-list look-ahead cost of the old method. The full-grid deflated Sharpe is **0.095**; the shortlist DSR is **0.904**. The 2018 midcap crash was a −19.68% loss versus −5.78% for the index. This is a credible systematic strategy in this sample, not a guaranteed anomaly.
