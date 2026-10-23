# Project MIP — Deep Codebase Analysis & Empirical Verification

**Subject:** `/mnt/sdcard/Subtitles/Project/Project_MIP_Colab`
**Version:** 2.4.0 · **HEAD:** `85c78e2` · **Analysis date:** 2026-10-23
**Method:** static reading, independent recomputation from SQLite, full test run, end-to-end pipeline execution, native-kernel benchmark, ledger reconciliation. Every number below was produced in this session; nothing is copied from the README unless explicitly labelled "claimed".

---

## 0. Verdict first

**The core engine works and is reproducible.** 565 of 571 tests passed on the original audit (6 environment-gated skips, 0 failures in 850s). The scanner, the Python backtester, the C99 kernel, the compliance engine and the report generators all execute successfully on real data. Accounting identities reconcile to the paisa, results are bit-deterministic across runs, and the ablation scorecard reproduces exactly.

**The audit findings have since been remediated.** The original audit identified a series of concrete defects the test suite did not catch: a silently broken pick-history writer, no historical point-in-time index constituents, an inconsistent delisting flag, calendar/data disagreements that leak into fills, a backtester that ignores the selected universe, a non-functional standalone RRG flow, a Telegram chunker that cannot split long lines, and tests that overwrite production deliverables. All were fixed in the 2026-10-23 remediation pass (§11), with regression tests and a full-suite rerun. Post-fix measurements: **574 passed, 5 skipped, 0 failed**.

The **canonical production backtest now runs on NIFTY500**, not the full database: **CAGR 30.01%, Sharpe 1.13, MaxDD −20.47% monthly / −27.70% daily, 604 trades**, all 604 entries on real exchange sessions. The ALL-symbol reference (including delisted names) is 29.59% / 1.06 / −23.65% / 703 trades. Same-engine survivorship measurement (all DB symbols vs survivors only) is **1.51 pp of CAGR** — see `reports/ENGINE_RECONCILIATION.md`.

The remaining limitation is data, not code: no historical index-constituent snapshots exist before October 2026, so historical index backtests are still survivorship-biased. The engine now refuses to hide that (`strict_point_in_time=True` raises; default runs set `survivorship_bias_risk=True` and log a warning).

---

## 1. What this system is

A single-tenant quantitative trading research platform for NSE India:

- **Data plane** — a 2.17M-row SQLite price store (2007→2026) with corporate-action adjustment, a trading calendar, benchmark CSVs, NSE bhavcopy ingestion, and a write firewall.
- **Strategy plane** — a 5-filter cross-sectional momentum screener (52-week-high retracement, 200 EMA trend, relative strength vs benchmark, 20 EMA market regime, positive Volar), deterministic ranking, sector caps, ATR risk-parity sizing, rank-hysteresis exits.
- **Simulation plane** — a pure-Python vector backtester for research and a C99 pthread/SIMD kernel over an in-memory tensor cube for parameter sweeps.
- **Institutional plane** — Brinson attribution, tail-risk suite, liquidity/capacity, SEBI pre-trade compliance, HTML tearsheets, 14-sheet Excel workbooks, zip bundles.
- **Interfaces** — a 2,045-line interactive CLI (`main.py`), a six-cell Colab notebook, headless production runner with file locking, cron daemon, Telegram dispatcher.

Layers and sizes (measured):

| Layer | Files | LOC | Role |
|---|---:|---:|---|
| `core/` | 25 | 12,852 | Data engine, scanner, portfolio, validation, reporting primitives |
| `scripts/` | 21 | 8,538 | Hardening, audits, orchestration, cloud sync, schedulers |
| `tests/` | 66 | 13,015 | 579 collected contracts |
| `brute_force/` | 7 | 2,938 | Tensor cube, ctypes bridge, grid generators, C kernel (856 lines C) |
| `colab/` | 5 | 1,085 | Notebook cockpit, environment staging |
| `nextgen/` | 8 | 1,037 | Residual momentum, vol targeting, delivery flow, DSR/PSR |
| `analytics/` | 4 | 588 | Institutional risk, Brinson, liquidity |
| `reporting/` | 3 | 495 | HTML tearsheet, bundle packager |
| `compliance/` | 2 | 331 | Pre-trade SEBI audit |
| `cache/` | 2 | 274 | Arrow/Parquet/Numpy cache |
| `main.py` | 1 | 2,045 | CLI dispatcher, 18 menu flows |
| **Total** | **144** | **43,198** | |

---

## 2. Data plane — what is actually in the database

`data/universe.db` (352,288,768 bytes, SHA-256 `2cea9700…e8b6ef`), read-only:

| Metric | Value |
|---|---:|
| Bars | **2,170,608** |
| Distinct symbols | **1,083** |
| Sessions | **4,890** |
| Date range | 2007-01-02 → **2026-10-19** |
| Active symbols on latest date | 1,032 |
| Delisted-flagged symbols / bars | 67 / 67,597 |
| `PRAGMA integrity_check` | **ok** |
| Duplicate `(symbol,date)` rows | **0** |
| NULL date/symbol/close | **0** |
| Non-positive closes | **0** |
| OHLC geometry violations | **414** (0.019%) |
| Applied corporate actions | 4 |
| `picks_history` rows | 180 |

The 414 geometry violations are exactly why `core/validation.py` exists: the scanner rejects malformed bars before factor computation rather than letting them poison rankings.

**Schema** (`prices`, `applied_corporate_actions`, `picks_history`, `sqlite_stat1`) with three indexes plus a unique `(symbol,date)` index. Writes to this file are blocked unless `MIP_ALLOW_PROD_MUTATION=1` (`core/data_engine.py:93-95`); operational writes go to `data/operational.db`.

**Auxiliary data:** four benchmark CSVs (NIFTY50/500/BANK/IT, 4,858–4,890 rows), a 4,889-session calendar (SHA-256 `4b3dce45…`), a corporate-action registry (SHA-256 `9e492f94…`, 3,889 bytes), 36 index catalogs, and 36 constituent snapshots.

---

## 3. Strategy plane — every rule, as implemented

### 3.1 Canonical configuration (`core/config.py`)

Frozen dataclass, SHA-256 fingerprint **`9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de`** (independently recomputed). Nine canonical scalars: lookback 252, retrace 0.80, trend EMA 200, RS EMA 200, regime EMA 20, top-N 20, exit buffer 40, sector cap 2, volatility floor 0.05 — plus ATR-14 / 2× stop / 1% risk.

### 3.2 Scan pipeline (`core/scanner.py`, 1,264 lines)

1. **Universe resolution** — `load_universe_constituents()` with 30-day cache TTL.
2. **Bar validation** — `ScannerDataValidator`: OHLC geometry, ≥252 bars (anti-IPO), NaN/zero checks, identity resolution.
3. **Corporate-action layer** — `AnalyticalPriceEngine` partitions or back-adjusts each series, point-in-time.
4. **Factors** — 252d return, annualized vol (floor 0.05), Volar = ret/vol, EMA-200, rolling 252d high, ATR-14, RS ratio and its EMA-200.
5. **Filters** — F1 `close ≥ 0.80 × high252`; F2 `close > EMA200`; F3 `RS > EMA200(RS)`; F4 regime; F5 `ret252 > 0 and Volar > 0`.
6. **Deterministic ranking** — Volar desc → ret252 desc → symbol asc; greedy sector cap.
7. **Regime + health gating** — if benchmark closes below its 20 EMA, every candidate is downgraded to `BEAR_HOLD`, `allow_buy=False`, `target_qty=0`.
8. **Reasons and quality** — every rejected symbol gets a reason code; coverage/health state machine writes `scan_quality.json/.md`.

### 3.3 Portfolio and execution (`core/portfolio.py`, 1,961 lines)

- Order lifecycle enum (`PENDING → FILLED/REJECTED/CANCELLED`), fill validation, session-date normalization in IST.
- Indian friction schedule (`FRICTIONS`): STT 0.10%, exchange turnover 0.00345%, GST 18% on brokerage+turnover, stamp duty 0.015%, brokerage 0.03%; plus configurable slippage (5 bps default).
- ATR risk parity: `risk_budget = NAV × 1%`, `risk/share = max(2×ATR14, 2% × price)`, `qty = min(floor(risk_budget/rps), floor(25% NAV/price))`, whole shares only.
- Exit hysteresis: retain while rank ≤ 40, above 0.80×52w-high and above EMA-200; otherwise sell next open.

### 3.4 Research backtester (`core/backtest.py`, 628 lines)

Monthly (or month-start) rebalance; signal at session close, **fill at next session's open**; whole shares; frictions + slippage; distress haircut ×0.50 for delisted names without a quote; daily and monthly equity curves; Sharpe with Rf=6.5%, Sortino, Calmar, recovery days.

### 3.5 Next-gen overlays (`nextgen/`)

- `residual_momentum.py` — Blitz/Baltussen residual momentum with 21-day reversal exclusion.
- `volatility_targeting.py` — EWMA realized vol → target scalar → dynamic cash shield.
- `delivery_flow.py` — CLV, delivery absorption, smart-money footprint, distribution veto.
- `vector_engine.py` — 2D `[T,N]` rolling high/EMA/ATR/vol; optional DuckDB (absent here, pandas fallback).
- `risk_statistics.py` — PSR, expected max Sharpe, **Deflated Sharpe Ratio**, factor attribution.
- `composite_alpha.py`, `profile.py` — MAD-z-scored composite alpha, user profile schema.

### 3.6 Simulation plane (`brute_force/`)

`build_tensor_cube()` precomputes `[date × symbol]` planes for open/close/high/low/volume, ATR-14, Volar for 4 lookbacks, 5 EMA spans, RS masks, regime flags, sector ids, volatility-target and delivery planes, plus five rebalance schedules. `bridge.py` maps Python dicts to packed C structs (64-byte params, 48-byte summaries) and calls `run_parallel_brute_force` under the GIL-free ctypes boundary. `sim_kernel.c` uses `pthread` + `stdatomic` work dispatch, `MAX_HOLDINGS=128`, 7 schedules, 8 filter bitmasks, and explicit `valid_price_mask` handling so halted bars are never traded.

### 3.7 Institutional plane

`analytics/institutional_risk.py` (Ulcer, UPI, Burke, Omega, Gain-to-Pain, Tail ratio, VaR/CVaR, tracking error, systematic/specific decomposition), `analytics/factor_attribution.py` (Brinson-Fachler with Menchero linking), `analytics/liquidity_analytics.py` (ADV-30, days-to-liquidate, Almgren-Chriss capacity), `compliance/pretrade_audit.py` (6 checks, SHA-256-signed manifest), `reporting/*` (interactive HTML, CRC-validated zip).

### 3.8 Interfaces

`main.py` exposes 18 flows (scan, Telegram, visuals, backtest, TDD, portfolio orders, auto-fetch, sector sync, breadth, RRG, DB audit, ETF scan, delivery, Excel regen, settings, all-indices batch, brute force, EOD desk). `scripts/run_production_pipeline.py` adds PID-tracked file locking and telemetry. `scripts/scanner_hardening.py` (1,503 lines) wraps the scanner with constituent reconciliation and coverage disposition.

---

## 4. Test suite — measured

```
571 collected
565 passed, 6 skipped, 0 failed, 1 warning — 850.28s (14m10s)
```

Skips are environment-gated: optional `plotly`, `curl_cffi`, `numba` are absent, plus artifact-conditional skips. Coverage includes 44 forensic-integrity tests, 29 ledger↔engine equivalence tests, 24 scanner-hardening tests, 19 adversarial-ranking tests, and defect regressions for three remediation loops.

No failures means the contracts the authors wrote are satisfied. §7 shows where the contracts themselves are too weak.

---

## 5. Empirical proof

### 5.1 Scanner — exact funnel and reproducible math

Fresh run on NIFTY500 as of 2026-10-19 (84.3s end-to-end, 62.0s scan):

| Stage | Count |
|---|---:|
| Requested constituents | 497 |
| Processed (validated) | **473** (95.17%) |
| Rejected: insufficient history (<252 bars) | 23 |
| Rejected: corporate-action review | 1 |
| Rejected: below 0.80 × 52w high | 274 |
| Rejected: below 200 EMA | 63 |
| Rejected: non-positive momentum | 16 |
| **Passed all filters** | **120** |
| Sector-capped output | 20 |

`274+63+16+23+1+120 = 497` — the funnel conserves exactly.

**Regime:** NIFTY500 closed 22,041.60 vs 20-EMA 22,236.31 → `DEFENSIVE`; therefore all 20 picks carry `allow_buy=False`, `target_qty=0`. The fail-closed path works.

**Independent factor recomputation** from raw bars for the top 10 (separate implementation, no scanner code):

| Symbol | Volar (reported / recomputed) | 252d return (reported / recomputed) | 52w high | ATR stop | Diff |
|---|---|---|---|---|---:|
| STLTECH | 10.511226 / 10.511226 | 6.487342 / 6.487342 | 1,051.10 | 777.96 | 0.0 |
| CUPID | 9.799943 / 9.799943 | 5.719818 / 5.719818 | 368.95 | 300.61 | 0.0 |
| WELCORP | 4.799710 / 4.799710 | 2.152963 / 2.152963 | 2,900.00 | 2,292.70 | 0.0 |
| HFCL | 4.785250 / 4.785250 | 2.480642 / 2.480642 | 275.91 | 240.85 | 0.0 |

EMA-200 also matches to 4 decimals once the same 550-day warmup window and `min_periods=200` are used. The scanner is not fabricating factors.

**Determinism:** two independent full scans produced byte-identical pick tables, SHA-256 `88b7148351…021be`.

### 5.2 Canonical backtest (2016-01-01 → 2026-08-31, production contract)

The canonical run now uses the **NIFTY500 universe** — the same universe as the strategy proof — not the full database. The ALL-symbol run is retained as a reference because it includes delisted names.

Top-20, buffer-40, sector-cap-2, ATR risk parity, 1% risk, 20 bps round-trip:

| Metric | ALL reference | **Canonical NIFTY500** |
|---|---:|---:|
| Universe size | 1,039 | **487** |
| Survivorship-bias flag | false | **true** |
| Final equity (₹10L start) | ₹1,58,67,075.04 | **₹1,64,23,508.95** |
| Total return | +1,486.71% | **+1,542.35%** |
| CAGR | +29.59% | **+30.01%** |
| Benchmark CAGR (NIFTY500) | +12.38% | +12.38% |
| Excess CAGR | +17.21% | **+17.63%** |
| Sharpe (Rf 6.5%) | 1.06 | **1.13** |
| Sortino | 1.41 | 1.49 |
| Calmar | 1.25 | **1.47** |
| Max drawdown (monthly) | −23.65% | **−20.47%** |
| Max drawdown (daily) | −34.80% | **−27.70%** (2020-03-23) |
| Closed trades | 703 | **604** |
| Win rate | 45.5% | 45.9% |
| Avg hold | 90.5 days | **106.5 days** |
| Deferred placeholder fills | 5 | **1** |
| Non-session dates filtered | 1 | **1** |
| Runtime | 136.5s | ~79s |

The canonical run differs from the ALL reference because index membership is ~half the breadth; per-symbol execution rules are unchanged. Both runs skip the 2026-05-01 non-session date and defer zero-volume fills to the next traded session.

**Strategy proof:** the random-test evidence, out-of-sample validation and optimal/low-drawdown settings are in `reports/STRATEGY_PROOF_AND_BEST_SETTINGS.md`. Cross-engine and cross-universe reconciliation is in `reports/ENGINE_RECONCILIATION.md`.

**Ablation cross-check (ALL, pre-fix):** the “Legacy MIP Baseline” row reran to CAGR 36.80%, Sharpe 1.03, MaxDD −49.74%, daily −57.04%, win 46.3%, final ₹28,264,374.69 — matching the published ₹28,264,375 to the rupee. The ablation scorecard must be regenerated against the fixed engine before quoting these rows again.

### 5.3 Ledger audit — accounting closes

From the canonical 604-trade NIFTY500 log, independently re-derived (`target_dates` = 2016-01-01 → 2026-08-31):

| Invariant | Result |
|---|---|
| Whole-share quantities | 604/604 integer, all > 0 |
| Positive entry/exit prices | 604/604 |
| Entry before exit, exit ≤ end date | 604/604 |
| `net_proceeds − cost_basis = net_pnl` | max error **₹0.01** |
| `return_pct` identity | max error **0.005 pp** |
| Friction + slippage recomputation | max error **₹0.005** |
| Compounded monthly returns vs equity ratio | **0.000000** error |
| CAGR identity | 0.013 pp error (rounding) |
| MaxDD identity | 0.004 pp error |
| Sharpe identity | 0.004 error |
| Win-rate identity | 45.86% vs 45.9% |
| Entries on authoritative calendar | **604 / 604** |
| Entries on zero-volume bars | **0** |

The ALL reference ledger (703 trades) closes the same way: PnL max error ₹0.01, return identity 0.005 pp, friction ₹0.005, compounding 0.000000, 703/703 calendar entries. Exit reasons on NIFTY500: 252 retracement stops, 20 EMA breaks, 41 no-data/rank-999999, remainder rank-buffer dropouts. No delisted-flagged symbol was ever held.

### 5.4 T+1 execution proof

Joined every fill to the raw bar for that symbol/date after the fix:

- Entries matching the **session open**: 604/604 (100%); zero-volume entries: **0**.
- Exits matching the session open: 602/602 joined rows (100%); zero-volume exits: **0**.
- All 604 entry dates lie on the authoritative trading calendar.
- Median relative difference from the open: **0.00e+00**.

The engine fills at the next traded session's open, not the signal close. Placeholder/holiday bars are no longer executable in either engine.

### 5.5 Native C99 kernel — parity, throughput, scaling

Cube: 501 symbols × 4,890 dates, 200.98 MB, built in 8.4–41.8s. One canonical NIFTY500 simulation: **7.387 ms** kernel latency.

960-configuration grid (4 lookbacks × 5 EMAs × 4 top-N × 4 buffers × 3 sector caps), same cube:

| Threads | Wall time | Configs/sec | Speedup |
|---:|---:|---:|---:|
| 1 | 8.32s | 115.3 | 1.00× |
| 2 | 4.16s | 231.0 | 2.00× |
| 4 | 3.35s | 286.4 | 2.48× |
| 8 | 3.01s | **319.2** | 2.77× |

`948 / 960` configurations produced distinct `(CAGR, MaxDD, trades)` signatures; 12 are genuine duplicates from equivalent parameter combinations. Zero NaN results. Host is a 3-core ARM64 device, so 8 threads oversubscribe — the 2.77× is memory-bandwidth-bound, not a kernel defect.

C engine metrics differ from the Python engine even on the same universe because execution/exit accounting differs: post-fix C/NIFTY500 2016-2026 = **27.39% CAGR / 38.32% daily MaxDD / 595 trades**; C/NIFTY750 = **28.13% / 34.63% / 639**; Python/NIFTY500 (canonical production) = **30.01% / 20.47% monthly (−27.70% daily) / 604**; Python/ALL = **29.59% / 23.65% / 703**. The full matrix is in `reports/ENGINE_RECONCILIATION.md`.

**§5.5 vs §9 D reconciliation (2026-10-23).** Both numbers are the same config, engine and universe, but they were produced by different harness paths. The previously published §9 D value of 28.69% was **equal-weight**, not ATR: the validation harness passed integer sizing code `0`, and `bridge.py:431` treated any non-string code as equal-weight. After the fix, the monthly-sampled ATR value is **26.81%** and the continuous ATR value is **27.39%**; they share the same ending equity (₹1,23,54,160) and the same 595 trades. The residual CAGR difference is annualization (`months/12` vs `(end_session−start_session)/252`); the drawdown difference is daily intra-period (38.32%) vs monthly rebalance sampling (20.69%). The Sharpe sub-gap is marked **INCOMPLETE** in the reconciliation artifact: T+1 period valuation moves 0.98 → 0.93, but the kernel does not expose its internal periodic return array, leaving ~0.02 unexplained rather than smoothed over.

The kernel also had a latent fail-closed bug: any session on which *all* holdings were masked (a market-wide holiday row) invalidated the entire multi-year simulation, and a rebalance with every entry masked did the same. Both are now local, non-fatal conditions — the engine forwards valuation from the prior finite close and skips the masked rebalance. The cube's `valid_price_mask` now also masks zero-volume placeholder bars (previously only genuinely missing bars).

### 5.6 Full institutional pipeline — end to end

`scripts/dispatch_institutional_pipeline.py --date 2026-10-19 --universe NIFTY500 --top-n 10`:

- Health: **7/7 checks, HEALTHY**.
- Constituent reconciliation: 501 total, 497 current, 4 missing (BAGMANE, BIRET, EMBASSY, DUMMYHEG — REITs/invITs and a dummy placeholder with no price data), coverage **99.20%**.
- Scan: 10 actionable candidates, sector distribution capped at 2; delivery veto excluded CUPID and AUROPHARMA; upper-circuit guard excluded HFCL.
- Risk: VaR-95 **2.00%**, CVaR-95 **2.81%**, Ulcer **1.96**.
- Liquidity: capacity **₹276.12 Cr**.
- Compliance: **6/6 COMPLIANT**, seal `70e478d1e1773e71…`.
- Tearsheet: 17,883-byte standalone HTML.
- Workbook: **14 sheets** (Dashboard … Charts).
- Bundle: 4,674,492 bytes, CRC `testzip() = None`, 9 members.
- Total wall time **101.38s**, exit 0.

### 5.7 Point-in-time corporate actions — proven both directions

PGIL 1:1 bonus, ex-date 2026-09-11:

| Query as-of | Treatment | 2026-09-09 close |
|---|---|---:|
| 2026-09-10 | `RAW_CONTINUOUS`, 0 actions | 2,277.90 (raw) |
| 2026-09-11 | `CONTINUOUS_BACKWARD_ADJUSTMENT`, 1 action | **1,138.95** (×0.5) |

The same history is unadjusted before the ex-date and halved on/after it — future actions are invisible, past history is consistent.

VEDL demerger, ex-date 2026-04-30: as-of 2026-04-29 `RAW_CONTINUOUS` (0 actions); as-of 2026-04-30 `BOUNDARY_HISTORY_PARTITIONING` (1 action), so pre-reorganisation history is severed rather than blended.

### 5.8 Module-level execution proof (direct, not test-mediated)

Every remaining subsystem was invoked directly and its output recomputed independently from the same inputs.

| Module | Independent check | Result |
|---|---|---|
| `analytics/institutional_risk.py` | 15 identities on the 127 monthly returns (CAGR, vol, VaR/CVaR 95/99, MaxDD, Calmar, Ulcer, Omega, G2P, tail, beta, alpha, R²) | **15/15 exact** |
| `analytics/factor_attribution.py` | Brinson single-period: active 0.800% = allocation 0.400% + selection 0.000% + interaction 0.400% | **exact** |
| `analytics/factor_attribution.py` | Menchero 2-period link: linked active −0.276% vs compounded active −0.276% | **diff 0.0** |
| `analytics/liquidity_analytics.py` | Per-row ADV-30, ADTV-30, days-to-liquidate, participation recomputed from raw bars | **4/4 exact** |
| `nextgen/residual_momentum.py` | 1,200×2 synthetic panel vs manual row-level recomputation at rows 600/800/1100 | **max diff 0.0** |
| `nextgen/residual_momentum.py` | 21-day skip: +5% shock in last 3 days moves score by only +0.097; short history returns zeros | **pass** |
| `nextgen/volatility_targeting.py` | EWMA vol on constant 1%/day: 15.87% (expected 15.87%); scalar 0.7559; bear → 0.0; integer scaling {100,33}→{50,16} | **exact** |
| `nextgen/delivery_flow.py` | CLV +1/−1/0/0; DAF 1.0; SMFI 5.24; veto/accumulate/neutral/NaN-fail-closed gates | **exact** |
| `cache/fast_cache.py` | store→get roundtrip equal; key stable for identical query, changes with symbols; oversized entry rejected; `clear()` empties manifest | **pass** |
| `scripts/cloud_sync.py` | 352,288,768-byte DB → 106,171,198 bytes (**69.86% saved**), decompress 3.3s, SHA-256 roundtrip match | **pass** |
| `main.py --option 12` | 16 DB invariants (NULLs, positivity, duplicates, indices) | **all pass, 12.81s, exit 0** |
| `main.py --option 13` | ETF engine: 79 instruments loaded, top 7 picks exported, 14 columns | **pass** |
| `main.py --option 14` | Delivery analytics: 3,335 rows, 13 columns, accumulation/distribution labels | **pass** |
| `main.py --option 11` | Standalone RRG after fix: 22 sectors → 1 LEADING / 2 IMPROVING / 5 WEAKENING / 14 LAGGING; 0 defaulted coordinates | **fixed** |
| `core/telegram_sender.py` | 9,500-char line → 3 chunks, max 3,986; `<pre>` block → 3 chunks, max 3,997; all ≤4,000 | **fixed** |

Risk-suite values on the post-fix canonical return stream: CAGR 29.85%, annualized vol 20.61%, VaR-95 8.41%, CVaR-95 12.07%, Ulcer 9.74, Omega 2.24, beta 0.74, annualized alpha 18.16%, R² 0.378. Every value matches an independent NumPy implementation to the reported precision.

---

## 6. Cross-cutting mechanics confirmed

- **Production write firewall:** read-only default; writes to `universe.db` raise unless `MIP_ALLOW_PROD_MUTATION=1`.
- **Config lineage:** each scan emits `scan_id`, timestamp, strategy/scanner/schema versions, `config_hash = 6c8981f9…` and candidate-level reason codes.
- **Artifact provenance:** workbook/CSV/JSON all carry as-of date and universe in the filename; the zip validates CRCs.
- **Fail-closed posture:** DEFENSIVE regime → zero buy authorizations; unhealthy benchmark → zero candidates; malformed bars → rejection with reason code.
- **Strategy significance:** the project's own DSR/PSR code on our exported monthly series gives DSR 0.954 (K=9) and PSR 0.9993; every published verdict is `NOT_STATISTICALLY_SIGNIFICANT` with `p_bonf = 1.0`. The codebase does not claim statistically significant alpha, and my reproduction supports that caution.

---

## 7. Findings — defects and gaps (all data-backed)

### 7.1 Pick-history writer is silently broken — FIXED
`core/scanner.py:156-186` does `CREATE TABLE IF NOT EXISTS` then inserts `ret_since`. `data/operational.db` already contains an incompatible `picks_history` (`ret_3m`, `ret_6m`, `ret_1y`, `exit_date`…, no `ret_since`). The insert raises, is swallowed by a broad `except`, and only logs `Failed to record picks history (table picks_history has no column named ret_since)`. Measured: operational table has **0 rows** after multiple scans. The “Pick Performance” workbook sheet therefore has no live source. Fix: migrate the table or align the DDL/columns.

### 7.2 No historical point-in-time index constituents — MITIGATED (data limitation)
`load_universe_constituents()` reads the *current* CSV with a 30-day TTL. `load_point_in_time_constituents()` works, but every snapshot in `data/constituent_snapshots.json` is dated **2026-10-12…2026-10-17**. For any historical `as_of_date`, it returns `None`, and `cube_builder` falls back to current membership. Consequence: historical simulations select from today's index, i.e. survivorship bias at the universe level. The code's own `point_in_time=True` path raises rather than silently degrading — the default path does not. This is open owner decision DECISION-02 in the audit notes.

**Measured consequence (2026-10-23).** The 2008 caveat ("~75 symbols, 7% coverage") is correct against the full database: 76 symbols have any 2008 bar (76/1,083 = 7.0%). Against the declared 501-symbol universe, only 74 have the required 252-bar history (14.8%); both denominators fail the 50% rule. The same measurement gives: **2008: 74/501 (14.8%) — DATA_INSUFFICIENT**; **2011: 81/501 (16.2%) — DATA_INSUFFICIENT**; **2018: 344/501 (68.7%) — VALID**; **2020: 362/501 (72.3%) — VALID**; **2016–2026: 471/501 (94.0%) — VALID**. The 2008 and 2011 stress rows therefore cannot support headline claims. A same-engine run (all DB symbols vs survivors only, config D) measures **1.51 pp of CAGR survivorship overstatement**; NIFTY500-vs-ALL (index membership plus breadth, not survivorship alone) is +0.39 pp. Full labels and the survivor/all run are in `reports/ENGINE_RECONCILIATION.md`.

### 7.3 Delisting flag is inconsistent — FIXED (code), DATA LEFT IMMUTABLE
67 symbols carry `is_delisted=1`, but the marker is not a delisting date:
- **20 symbols** (ABAN, RCOM, RELINFRA, RHFL, HDIL, FLFL, …) are flagged for all history through **2026-09-11**, then unflagged from **2026-09-15** — a bulk reflag while they still trade. Example: ABAN has 1,163 flagged bars ending 2026-09-11 and 24 unflagged bars through 2026-10-19.
- Only 47 of the 67 genuinely stop quoting before 2026.
- `README` claims `JETAIWAYS` is preserved — the symbol has **0 bars** in the database.

Effect: delisting/salvage logic cannot be exercised on real delisted names, and any `is_delisted`-based haircut is unreliable for the 20 mixed symbols.

### 7.4 Calendar and price data disagree — FIXED
Authoritative calendar: 4,889 sessions ending 2026-10-16. Database: 4,890 sessions ending 2026-10-19.

| Date | In DB | In calendar | Bars |
|---|---|---|---:|
| 2026-05-01 (Maharashtra Day) | yes | **no** | 667 placeholder bars (O=H=L=C, volume 0) |
| 2026-10-19 | yes | **no** (calendar stale) | 1,032 |
| 2026-10-02 (Gandhi Jayanti) | **no** | yes | 0 |

The Python backtester derives execution dates from `sorted(bars["date"].unique())`, not the calendar, so **11 entries executed on 2026-05-01** at the previous close. Across the full run, **12 entries and 2 exits** priced on zero-volume bars (DIACABS, 11 names on 2026-05-01, GVT&D). The C kernel has `valid_price_mask` and refuses to trade halted bars; `core/backtest.py` has no equivalent mask. Impact is small (1.7% of entries) but it contradicts the “T+1 open” guarantee and the “authoritative calendar” claim.

### 7.5 Research backtester ignores universe selection — FIXED
`LightweightBacktester.run()` now accepts `universe_mode` and filters to the selected index. The **canonical run uses NIFTY500** (487 resolved symbols, 604 trades, `survivorship_bias_risk=True`); the ALL-symbol run remains available as a reference (1,039 symbols, 703 trades). The earlier mismatch — 120 of 362 traded symbols (33%) and 223 of 703 trades (32%) outside the current NIFTY500 — was measured before the fix. The C engine also filters (NIFTY500 = 501 symbols); C/NIFTY500 27.39% vs Python/NIFTY500 30.01% is now an **engine** difference (execution/exit accounting), not a universe difference, and both rows are labelled in `reports/ENGINE_RECONCILIATION.md`.

### 7.6 Tests mutate production deliverables — FIXED
`tests/test_backtest_monthly_returns.py` instantiates `LightweightBacktester(base_dir=PROJECT_ROOT)` and runs a 2023–2024 simulation, which **overwrites** `reports/backtest_results.json` and `reports/trade_log.csv`. I observed this live: a test run replaced the then-canonical ledger with a 38-trade test ledger. Anyone running `pytest` after a production run silently loses the production artifacts. Earlier isolation work covered only `scan_quality.md` and `constituent_snapshots.json`.

### 7.7 Documentation drift — FIXED
- “25 core modules” counts `__init__.py`; there are 24 modules. The README table also names `market_breadth.py` and `ui.py`; actual files are `breadth.py` and `visuals.py`.
- Row count 2,164,420 is stale (actual 2,170,608).
- Database SHA-256 in README (`0077ea77…`) does not match the current file (`2cea9700…`) — expected after data updates, but the badge still presents it as current.
- `core/excel_generator.py` docstring says “12-Sheet”; it emits 14.

### 7.8 Working tree is dirty — CLOSED (tagged)
The original audit found HEAD `85c78e2` with 19 tracked files modified and `pytest.ini` untracked, so the results described the working tree rather than a commit. The 2026-10-23 reconciliation changes are committed and tagged **`v2.4.1-audit-reconciled`**; the canonical artifacts were regenerated after the suite finished, and `git status` is clean at the tag.

### 7.9 Optional dependencies absent — INFO (unchanged)
`duckdb`, `pyarrow`, `yfinance`, `plotly`, `curl_cffi`, `numba` are not installed. The code falls back gracefully (pandas indicators, cached ETF prices, 6 skips), but the DuckDB/Arrow acceleration paths and live ETF pricing were not exercised here.

### 7.10 Cache size limit is advisory — FIXED
`FastDataCache(max_cache_size_mb=1)` enforces the limit *before* writing a new entry. Measured: a single 60,000×4 frame produced a 1.73 MB `.npz` on a 1 MB budget, and every previously cached entry was evicted to make room. The limit is therefore a soft cap that one oversized entry can exceed indefinitely.

### 7.11 CLI `--option` numbering does not match the menu — FIXED
`--help` says “Run option directly without menu (1-18)”, but `main()` uses a different map than `build_menu_handlers()`: menu `[7]` is the DB audit while CLI `--option 7` is portfolio rebalancing; menu `[6]` is settings while CLI `--option 6` is the TDD suite. Running `--option 7` with the default ₹1L capital hit a legitimate fail-closed guard (`capital < MTM NAV ₹1,24,101.90`) and exited with an uncaught `ValueError` traceback instead of a clean error. Running the intended audit required `--option 12`.

### 7.12 Standalone RRG flow is non-functional — FIXED
`run_standalone_sector_rrg()` calls `compute_sector_rotation()` with raw bars but never calls `compute_rrg_metrics()`. The engine therefore falls back to `rrg_rs_ratio = rrg_rs_momentum = 100.0` for every sector, and `classify_quadrant(100, 100)` returns `LEADING`. Measured output: **22/22 sectors LEADING**, all with RRG 100.0/100.0, versus the scanner-integrated run on the same date which correctly produced 2 LEADING, 3 IMPROVING, 5 WEAKENING, 10 LAGGING. The CLI printer also looks for `breadth_pct`/`pct_above_200ema`, which the engine never emits (the actual key is `breadth_200_pct`), so it prints `0.0%` breadth for sectors whose JSON says 75%.

### 7.13 Telegram chunker does not split long lines — FIXED
`_chunk_message(text, 4000)` only breaks at newlines. Measured:

| Input | Chunks | Max chunk | Over Telegram limit |
|---|---:|---:|---|
| 9,500-char single line | 1 | 9,500 | **yes** |
| 9,011-char `<pre>` block | 1 | 9,011 | **yes** |
| 26,000 chars of short lines | 7 | 3,990 | no |
| 9,499 chars + trailing `\n` | 2 | 9,499 | **yes** |

A single long line or `<pre>` block is passed through unsplit and would be rejected by the Telegram API. Multi-line chunking also drops the newline at each chunk boundary and any trailing newline.

---

## 8. What is genuinely strong

1. **Accounting discipline.** Whole shares, explicit friction model, t+1 opens, and identities that close to ₹0.01. Most retail backtesters fail here.
2. **Fail-closed behavior.** Bear regime, stale benchmark, bad bars, unresolved corporate actions all suppress buys rather than guessing.
3. **Determinism.** Identical scanner output hash across runs; exact reproduction of published ablation rows.
4. **Point-in-time corporate actions.** Correct in both directions, with partition-vs-adjust semantics.
5. **Simulation performance.** 7.4 ms per 10-year simulation and 319 configs/sec on a 3-core phone-class ARM64 device, with clean parallel scaling.
6. **Honest statistics.** The project computes DSR/PSR and labels its own features not significant instead of marketing them.

---

## 9. Reproduction commands

```bash
cd /mnt/sdcard/Subtitles/Project/Project_MIP_Colab

# 1. Full contract suite (expect 574 passed, 5 skipped, 0 failed)
python3 -m pytest -q

# 2. Live scan (NIFTY500, 2026-10-19)
python3 - <<'PY'
from core.scanner import PydroidScanner
from pathlib import Path
sc = PydroidScanner(Path('.').resolve())
top, breadth, sectors, regime, etfs, delivery = sc.run_scan(
    as_of_date="2026-10-19", universe_mode="NIFTY500", top_n=20,
    export_csv=True, export_excel=False, auto_update_universe=False,
    allow_stale_data=True, send_telegram=False)
print(len(top), regime["regime"])
PY

# 3. Canonical production backtest
python3 - <<'PY'
from core.backtest import LightweightBacktester
from pathlib import Path
r = LightweightBacktester(Path('.').resolve()).run(
    start_date="2016-01-01", end_date="2026-08-31", top_n=20, exit_buffer=40,
    use_regime_filter=True, max_per_sector=2, sizing_mode="atr_risk_parity",
    risk_per_trade_pct=1.0, universe_mode="NIFTY500")
print(r["cagr_pct"], r["sharpe_ratio"], r["max_drawdown_pct"], r["total_trades"])
PY

# 4. End-to-end institutional pipeline
python3 scripts/dispatch_institutional_pipeline.py \
  --date 2026-10-19 --universe NIFTY500 --benchmark NIFTY500 --top-n 10 --allow-stale

# 5. Native kernel smoke test + sweep
python3 scripts/run_blazing_brute_force.py

# 6. Cross-engine reconciliation + canonical artifacts
python3 reports/analysis_evidence/canonical_backtest.py
python3 reports/analysis_evidence/summarize_candidates.py
python3 reports/analysis_evidence/reconcile_engines.py
python3 reports/analysis_evidence/label_random_windows.py
```

---

## 10. Bottom line

The engineering core is real: the data, factors, ledger, C kernel, compliance and reporting all do what the code says, and the numbers reproduce. The project is a credible research workstation.

The 2026-10-23 remediation pass fixed every code-level defect in §7 and added regression coverage. The canonical production backtest is now NIFTY500 (30.01% CAGR, 604 trades). The remaining material limitation is data: historical index-constituent snapshots do not exist before October 2026, so historical index backtests remain survivorship-biased — now explicitly flagged, enforceable via `strict_point_in_time=True`, and **measured at 1.51 pp of CAGR** in a same-engine survivor/all run. Stress windows are labelled: 2008 and 2011 are DATA_INSUFFICIENT and excluded from headline claims; 2018 and 2020 are VALID with matched strategy/benchmark windows. The tree is committed and tagged `v2.4.1-audit-reconciled`.

---

## 11. Remediation log — 2026-10-23

| Finding | Fix | Files | Verification |
|---|---|---|---|
| 7.1 pick-history writer | Added `ensure_picks_history_schema()`: creates the table, `ALTER TABLE` adds missing columns, creates a unique key; commits picks before enrichment and queries prices from the universe DB instead of the operational DB | `core/scanner.py` | Real scan wrote **20 rows** for 2026-10-19 and retained/updated 5 historical rows; migration unit test |
| 7.2 PIT constituents | Added `strict_point_in_time` (raises), `universe_point_in_time` / `survivorship_bias_risk` metadata, and explicit warnings; same flag on the C tensor cube and runner | `core/backtest.py`, `brute_force/cube_builder.py`, `brute_force/runner.py` | Strict mode raises `NO_POINT_IN_TIME_SNAPSHOT`; default NIFTY500 run returns `survivorship_bias_risk=True` |
| 7.3 delisting flags | Delisted set now derived from each symbol's last observed bar (plus a final-row flagged check), not the bulk-refreshed per-row flag | `core/backtest.py` | `ABAN`/`RCOM` excluded from `delisted_symbols`; regression test |
| 7.4 calendar/fills | Execution dates now intersect the authoritative calendar (dates after calendar max retained); zero-volume bars excluded from execution maps; per-symbol fill deferral to the next traded session | `core/backtest.py`, `brute_force/cube_builder.py`, `brute_force/sim_kernel.c` | **0** entries/exits on 2026-05-01; 604/604 canonical NIFTY500 entries on calendar sessions (703/703 on the ALL reference); C kernel no longer invalidates on market-wide halt rows |
| 7.5 universe ignored | Added `universe_mode` to `run()`, wired `--universe` through the CLI, and emitted universe/PIT metadata | `core/backtest.py`, `main.py` | NIFTY500 run: `universe_size=487`, `survivorship_bias_risk=True`; ALL run unchanged |
| 7.6 tests clobber reports | Added `output_dir` to `LightweightBacktester`; isolated the three tests that ran against `reports/` | `core/backtest.py`, `tests/test_backtest_monthly_returns.py`, `tests/test_end_goal_charter.py`, `tests/test_benchmark_selection.py` | Canonical `trade_log.csv` remains 604 rows after a full suite run |
| 7.7 documentation drift | Corrected row/symbol counts, DB hash, module names/count, calendar sessions, test count, Excel sheet count, CLI map, JETAIWAYS claim, and made the banner version/Python dynamic | `README.md`, `core/excel_generator.py`, `main.py` | `--help` shows both option maps; banner reads `v2.4.0` and the real Python version |
| 7.10 cache limit | Reject a single entry larger than the budget and re-enforce the limit after each store | `cache/fast_cache.py` | 1.73 MB entry rejected on a 1 MB budget; small entry retained |
| 7.11 CLI numbering | Added `--menu-option` using menu numbering, documented the headless map, and wrapped dispatch in clean error handling | `main.py` | `tests/test_fixes_2026_10_23.py::test_fix08`; `--option 7` now prints a clean guard message |
| 7.12 standalone RRG | Engine computes RRG metrics when the snapshot lacks them; printer reads `breadth_200_pct` | `core/sector_rotation.py`, `main.py` | 22 sectors → 1 L / 2 I / 5 W / 14 Lg; 0 defaulted coordinates |
| 7.13 Telegram chunker | Rewrote chunking with preserved line endings, hard-splitting of long lines, and balanced `<pre>` across chunks | `core/telegram_sender.py` | 9,500-char line → 3 chunks, max 3,986; `<pre>` block → 3 chunks, max 3,997; lossless for plain text |
| 7.14 §5.5 vs §9 D divergence | `bridge.py` now accepts integer sizing codes (0=ATR, 1=equal weight) as well as strings; evidence harnesses pass the real sizing name | `brute_force/bridge.py`, `reports/analysis_evidence/validate_candidates.py`, `validate_low_dd.py`, `random_robustness.py` | Old 28.69% row was equal-weight; corrected ATR monthly 26.81%, continuous 27.39%, same ending equity and 595 trades |
| 7.15 Stress-window comparability | Strategy and benchmark curves share the same base rebalance; each window records `strategy_months == benchmark_months`; every window labelled from measured 252-bar coverage | `reports/analysis_evidence/validate_candidates.py`, `reconcile_engines.py` | COVID 5 vs 5 months (was 5 vs 4); 2018 12 vs 12; all `aligned=True` |
| 7.16 Canonical universe | Canonical production run now `universe_mode="NIFTY500"`; ALL retained as reference | `reports/analysis_evidence/canonical_backtest.py`, `core/backtest.py` docs | NIFTY500 30.01% / 604 trades; ALL 29.59% / 703 |
| 7.17 `ALL` tensor cube was empty | `load_universe_constituents("ALL")` intentionally returns an empty set (no filter); `cube_builder` now enumerates every DB symbol and avoids SQLite variable limits | `brute_force/cube_builder.py` | ALL cube: 1,083 symbols, 2.17M bars; survivorship run completes |
| 7.18 Random-window harness added months to a *daily index* | Window end now uses a calendar month offset, not `s + months`; JSON encoder handles NumPy integers | `reports/analysis_evidence/random_robustness.py` | Windows are 2–5 years; no billion-percent outliers |
| 7.19 Survivorship bias was a literature range | Measured two same-engine/same-config runs: all DB symbols vs symbols still quoting after 2026-08-31 | `reports/analysis_evidence/reconcile_engines.py` | **1.51 pp CAGR** (27.00% → 28.51%), 50 dead names |

**Regression suite added:** `tests/test_fixes_2026_10_23.py` (8 tests) covering the migration, cache rejection, chunker, calendar/universe/delisting metadata, strict PIT, standalone RRG, and the CLI parser. The ATR-vs-equal-weight contract test was extended in place to assert integer/string sizing equivalence.

**Full suite after fixes:** `574 passed, 5 skipped, 0 failed` in 1,356s. New tests: +8; updated contracts: mask forward-fill behavior (3 tests) and chunker losslessness.

**Post-fix canonical artifacts regenerated:** Python 2016–2026 NIFTY500 run (CAGR 30.01%, Sharpe 1.13, MaxDD −20.47% monthly / −27.70% daily, 604 trades), trade ledger audit (all identities intact, 604/604 calendar entries), `reports/analysis_evidence/04_backtest.json`, `05_ledger_audit.json`, `21_strategy_validation.json` (aligned windows, ATR sizing), `22_candidate_engine_summaries.json`, `33_reconciliation.json`, `33b_random_window_quality.json`, and `34_python_canonical.json`. The ALL reference remains 29.59% / 703 trades in `04b_backtest_all.json`.
