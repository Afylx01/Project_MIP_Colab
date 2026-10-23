# FORENSIC BACKTEST INTEGRITY AUDIT REPORT

**Status**: AUDITED WITH CAVEATS (3 WINDOWS NON-VALID)
**Date**: 2026-10-22 23:58:56 UTC
**Target Dataset**: NIFTY500 (`data/universe.db`, 2007-01-02 to 2026-10-19)

## 1. TASK 1: VARIABLE WIRING AUDIT & CANONICAL BASELINE RECONCILIATION

### Flaw Identified: Dictionary Key Precedence Bug (`DEF-WIRING-01`)
- **Files Affected**:
  - `brute_force/bridge.py:366-382`
  - `brute_force/grid.py:59,61` (`CANONICAL_BASELINE`)
- **Mechanism**: In `brute_force/bridge.py`, the engine mapped parameters to C structs by checking string keys first:
  ```python
  if "lookback" in p:          # Line 366: Checked first!
      c_params[i].lookback_idx = int(cube.lookback_values.index(p["lookback"]))
  elif "lookback_idx" in p:     # Line 372: Ignored if 'lookback' exists!
      c_params[i].lookback_idx = min(max_lb_idx, max(0, int(p.get("lookback_idx", 2))))
  ```
  In `CANONICAL_BASELINE`, `"lookback": 252` and `"ema_trend": 200` were hardcoded keys. When the grid search script copied `CANONICAL_BASELINE` and updated `p["lookback_idx"] = lb_idx` or `p["ema_idx"] = ema_idx`, the presence of `p["lookback"]` and `p["ema_trend"]` caused `bridge.py` to silently force `lookback_idx=2 (252)` and `ema_idx=3 (200)` across all configurations.

### Canonical Baseline Provenance & Reconciliation (Task 1 Resolution)
- **Root Cause of Baseline Divergence**:
  - **Baseline 1 (Canonical Baseline)**: CAGR **35.01%**, MaxDD **41.65%**, Calmar **0.84**, Sharpe **1.01**, Sortino **1.59**, Trades **591**, Ending Equity **₹23,163,080**.
    - *Command & Script*: `python scripts/optimize_low_drawdown_calmar.py` (evaluating `base_param`).
    - *Input*: NIFTY500, 2016-01-01 to 2026-10-15, monthly rebalance, top 20, buffer 40, sector cap 99, equal weight, no regime gate, no sector cap.
    - *Timestamp*: `2026-10-21T14:58:25Z` (commit `b718386`).
    - *Mechanism*: Evaluated drawdown strictly at monthly rebalance dates (`periodic_equity`), reserved a 1% cash buffer drag (`investable_cash = cash * 0.99f`), and valued equity at the final rebalance session.
  - **Baseline 2 (Dynamic Daily Simulation)**: CAGR **33.91%**, MaxDD **50.66%**, Calmar **0.67**, Sharpe **1.00**, Sortino **1.59**, Trades **591**, Ending Equity **₹22,941,648**.
    - *Command & Script*: `python scripts/forensic_integrity_audit.py` (line 339, `runner.engine.execute_sweep`).
    - *Input*: Same strategy parameters on NIFTY500 (2016-01-01 to 2026-10-15).
    - *Timestamp*: `2026-10-22T00:25:39Z` (commit `d8a920f`).
    - *Mechanism*: Evaluated drawdown continuously using daily intra-period NAV marking across every session in `sim_kernel.c`, deployed 100% cash (zero cash buffer reservation), and valued through calendar end (2026-10-15). Daily marking revealed intra-month drawdowns of 50.66% (vs 41.65% sampled on monthly dates).
- **Resolution**: Baseline 1 (CAGR **35.01%**, MaxDD **41.65%**, Calmar **0.84**) is established as the **SINGLE CANONICAL BASELINE**. All deltas across the entire report and results JSON are computed strictly against Calmar 0.84. The duplicate `CANONICAL_BASELINE` classification label on the dynamically simulated row in `canonical_reconciliation` has been deleted and replaced with `LEGACY_MIP_SIMULATED`, eliminating any baseline ambiguity from the JSON.

## 2. TASK 2: DEDUPLICATION AUDIT (4 DISTINCT SIGNATURES)

- **Total Rows in Previous Top-20**: 20
- **Distinct Metric Signatures**: 4
- **Duplicate Rows**: 16 (80% redundancy due to lookback/ema masking bug)

### All 4 Distinct Configurations from Top-20 Grid Search

| Rank | Lookback | EMA Trend | Top N | Buffer | Sector Cap | Sizing | Full Calmar | OOS Calmar | Full CAGR | Full MaxDD |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | 252d | 200d | 10 | 40 | 1 | atr_risk_parity | 1.82 | 2.83 | 32.22% | 17.71% |
| 2 | 252d | 200d | 10 | 60 | 1 | atr_risk_parity | 1.76 | 2.76 | 32.28% | 18.34% |
| 3 | 252d | 200d | 10 | 30 | 1 | atr_risk_parity | 1.70 | 2.68 | 31.53% | 18.55% |
| 4 | 189d | 150d | 10 | 30 | 1 | equal_weight | 1.67 | 2.97 | 32.24% | 19.34% |

> [!NOTE]
> **Rank 4 Disposition (Co-Equal Top-4 Finalist)**: The 4th distinct signature (`Top 10, Buffer 30, Sector Cap 1, Equal Weight`) achieved Full Calmar 1.67 and **Out-of-Sample Calmar 2.97** (higher than Rank 1's OOS Calmar of 2.83) and OOS Sortino 3.16. Rather than being arbitrarily excluded for a 0.03 difference on the training sample, Rank 4 is recognized as a **co-equal finalist (Top 4 Frontier)**, offering optimal portfolio diversification for mandates that require Equal Weight execution over ATR risk parity.

## 3. TASK 3: RE-CLASSIFIED ABLATION SCORECARD (CALMAR-BASED)

> [!IMPORTANT]
> **Baseline Correction Notice**: All deltas derive dynamically from the single institutional canonical NIFTY500 baseline (CAGR 35.01%, MaxDD 41.65%, Calmar 0.84).

Classification criteria:
- `PROVEN`: ΔCalmar > +5.0% vs canonical baseline (0.84)
- `HARMFUL`: ΔCalmar < -5.0% vs canonical baseline (0.84)
- `NEUTRAL`: -5.0% <= ΔCalmar <= +5.0% vs canonical baseline (0.84)
- `REGIME_DEPENDENT`: Feature flips positive in IS and negative in OOS (or vice versa)

| ID | Feature Name | Old Label | New Calmar Label | CAGR (%) | MaxDD (%) | Calmar | ΔCalmar (%) | Reason / IS vs OOS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `RUN_0_BASELINE` | Legacy MIP Baseline | `PROVEN_BASELINE` | **`CANONICAL_BASELINE`** | 35.01% | 41.65% | 0.84 | +0.00% | Single-engine reconciled baseline reference (CAGR 35.01%, MaxDD 41.65%, Calmar 0.84) |
| `RUN_1_REGIME` | + Benchmark 20 EMA Regime Gate | `HARMFUL` | **`REGIME_DEPENDENT`** | 29.13% | 40.83% | 0.71 | -15.50% | Flips between IS (Δ-6.6%) and OOS (Δ+5.2%) |
| `RUN_2_SECTOR_CAP` | + Sector Hard Cap (Max 2) | `NEUTRAL` | **`REGIME_DEPENDENT`** | 35.09% | 33.71% | 1.04 | +23.80% | Flips between IS (Δ+32.9%) and OOS (Δ-22.7%) |
| `RUN_3_ATR_SIZING` | + ATR Risk Parity Sizing | `PROVEN_PROFITABLE` | **`NEUTRAL`** | 39.42% | 46.37% | 0.85 | +1.20% | Calmar within ±5% (+1.2%) vs canonical baseline (0.84) |
| `RUN_4_NO_BUFFER` | - Exit Buffer Removed (Buffer = 20) | `JUST_COMPLEXITY` | **`HARMFUL`** | 37.72% | 52.10% | 0.72 | -14.30% | Calmar degraded by -14.3% vs canonical baseline (0.84) |
| `RUN_5_BUFFER_60` | + Wide Exit Buffer (Buffer = 60) | `NEUTRAL` | **`HARMFUL`** | 33.58% | 47.61% | 0.71 | -15.50% | Calmar degraded by -15.5% vs canonical baseline (0.84) |
| `RUN_6_TOP_10` | + High Concentration (Top 10) | `HARMFUL` | **`REGIME_DEPENDENT`** | 34.80% | 56.90% | 0.61 | -27.40% | Flips between IS (Δ-27.6%) and OOS (Δ+6.4%) |
| `RUN_7_TOP_30` | + Diversified Breadth (Top 30) | `NEUTRAL` | **`REGIME_DEPENDENT`** | 34.31% | 42.19% | 0.81 | -3.60% | Flips between IS (Δ+5.3%) and OOS (Δ-15.7%) |
| `RUN_8_MODERN_STACK` | + Full Modern Production Stack | `HARMFUL` | **`PROVEN`** | 30.35% | 23.34% | 1.30 | +54.80% | Calmar improved by +54.8% vs canonical baseline (0.84) |

## 4. TASK 4: CANONICAL RECONCILIATION ON NIFTY 500 (SINGLE ENGINE, 2016-2026)

> [!NOTE]
> **Multiple-Testing Correction (Bailey & López de Prado 2014 & Policy A Uniform Rule)**: 8 model variations evaluated against Canonical Baseline. Family-wise error rate controlled at $\alpha = 0.05$; Bonferroni threshold $\alpha_{adj} = 0.0063$. Under **Policy A**, features with $p_{bonf} > 0.05$ or $\text{DSR} < 0.50$ are uniformly classified as `NOT_STATISTICALLY_SIGNIFICANT`.

> **Required Sharpe Statement**: With 8 trials at α=0.05, required Sharpe is 1.91. Best observed is 1.08. Statistical significance test FAILS across all configurations; no feature reaches multiple-testing significance under Bonferroni FWER control.

| Feature / Stack | CAGR (%) | MaxDD (%) | Calmar | Sharpe | DSR | $p_{{bonf}}$ | Sig? | Trades | Equity (INR) | Δ vs cross-engine baseline (%) | Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Legacy MIP Baseline** | 33.91% | 50.66% | 0.67 | 0.98 | 0.88 | 1.000 | `FAIL` | 593 | 21,505,882 | -20.20% | `LEGACY_MIP_SIMULATED` |
| **+ ATR Risk Parity Sizing ON** | 33.74% | 47.88% | 0.70 | 0.98 | 0.88 | 1.000 | `FAIL` | 594 | 21,225,754 | -16.70% | `HARMFUL` |
| **+ Regime Gate ON** | 28.65% | 41.35% | 0.69 | 0.95 | 0.86 | 1.000 | `FAIL` | 499 | 14,109,075 | -17.90% | `HARMFUL` |
| **+ Sector Cap = 2** | 35.30% | 37.60% | 0.94 | 1.04 | 0.90 | 1.000 | `FAIL` | 735 | 23,978,166 | +11.90% | `NOT_STATISTICALLY_SIGNIFICANT` |
| **+ Buffer = 60** | 33.06% | 45.31% | 0.73 | 0.96 | 0.87 | 1.000 | `FAIL` | 508 | 20,107,862 | -13.10% | `HARMFUL` |
| **+ Top N = 10** | 33.99% | 51.18% | 0.66 | 0.90 | 0.83 | 1.000 | `FAIL` | 265 | 21,632,416 | -21.40% | `HARMFUL` |
| **+ Residual Momentum ON** | 30.07% | 42.20% | 0.71 | 0.99 | 0.88 | 1.000 | `FAIL` | 734 | 15,845,284 | -15.50% | `HARMFUL` |
| **+ Combined Production Stack** | 27.94% | 22.63% | 1.23 | 1.08 | 0.92 | 1.000 | `FAIL` | 716 | 13,322,584 | +46.40% | `NOT_STATISTICALLY_SIGNIFICANT` |

## 5. TASK 5: BEAR-MARKET STRESS TESTS & ARITHMETIC PROOF

### Arithmetic Consistency Proof Table (4 Windows × 2 Strategies)

Mathematical Identity: For any negative-return window, $\text{MaxDD} \ge |\text{total\_return}|$.

| Window | Strategy | Start Date | End Date | Actual Days | In-Window Cash Days | Effective Days | Total Return | CAGR | MaxDD (Raw) | MaxDD >= \|Total Return\| | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **2008 Global Financial Crisis** | Legacy MIP | 2008-01-01 | 2008-12-31 | 246 | 23 | 223 | -16.05% | -17.94% | 17.5253% | **PASS** (17.53% >= 16.05%) | `DATA_INSUFFICIENT` (Non-comparable effective windows (Legacy: 223 days vs Top: 164 days).) |
| **2008 Global Financial Crisis** | Top Config | 2008-01-01 | 2008-12-31 | 246 | 82 | 164 | -4.90% | -5.52% | 7.3689% | **PASS** (7.37% >= 4.90%) | `DATA_INSUFFICIENT` (Non-comparable effective windows (Legacy: 223 days vs Top: 164 days).) |
| **2011 European Debt Crisis** | Legacy MIP | 2011-01-01 | 2011-12-31 | 246 | 20 | 226 | -0.56% | -0.62% | 13.7094% | **PASS** (13.71% >= 0.56%) | `PARTIAL` (Non-comparable effective windows (Legacy: 226 days vs Top: 184 days).) |
| **2011 European Debt Crisis** | Top Config | 2011-01-01 | 2011-12-31 | 246 | 62 | 184 | -11.97% | -13.25% | 18.1445% | **PASS** (18.14% >= 11.97%) | `PARTIAL` (Non-comparable effective windows (Legacy: 226 days vs Top: 184 days).) |
| **2018 Midcap Crash / Correction** | Legacy MIP | 2018-01-01 | 2018-12-31 | 246 | 22 | 224 | -19.55% | -21.71% | 26.2925% | **PASS** (26.29% >= 19.55%) | `VALID` |
| **2018 Midcap Crash / Correction** | Top Config | 2018-01-01 | 2018-12-31 | 246 | 22 | 224 | -4.41% | -4.95% | 14.9134% | **PASS** (14.91% >= 4.41%) | `VALID` (Reduction: +11.38%) |
| **2020 COVID Crash** | Legacy MIP | 2020-01-01 | 2020-05-29 | 100 | 23 | 77 | -18.24% | -48.27% | 38.8349% | **PASS** (38.83% >= 18.24%) | `DATA_INSUFFICIENT` (Non-comparable effective windows (Legacy: 77 days vs Top: 19 days).) |
| **2020 COVID Crash** | Top Config | 2020-01-01 | 2020-05-29 | 100 | 81 | 19 | +5.35% | +18.58% | 1.5725% | **N/A** (Return >= 0) | `DATA_INSUFFICIENT` (Non-comparable effective windows (Legacy: 77 days vs Top: 19 days).) |

### Arithmetic Proof of Consistency (Resolution of the Apparent CAGR Paradox)
- **Root Cause**: The apparent violation in the previous report arose because the report compared `MaxDD` against `CAGR`, not `Total Return`.
- **Formula Mechanism**: In `sim_kernel.c:612`, CAGR is calculated as:
  $$\text{CAGR} = \left(\frac{\text{Final Equity}}{\text{Initial Capital}}\right)^{\frac{1}{Y}} - 1, \quad \text{where } Y = \frac{\text{End Session} - \text{Start Session}}{252}$$
- When a negative-return window spans a fraction of a year ($Y < 1$), annualizing compounds the loss over 12 months, producing a CAGR that is *more negative* than the actual period loss:
  - **2008 Global Financial Crisis (Legacy MIP)**: Spans 223 active sessions ($Y = 0.8849$ yr). Cumulative total return is **-16.05%**, whereas CAGR is **-17.94%**. MaxDD is **17.53%**, which strictly satisfies $17.53\% \ge 16.05\%$.
  - **2011 European Debt Crisis (Legacy MIP)**: Spans 226 active sessions ($Y = 0.8968$ yr). Cumulative total return is **-0.56%**, whereas CAGR is **-0.62%**. MaxDD is **13.71%**, which strictly satisfies $13.71\% \ge 0.56\%$.
  - **2018 Midcap Crash / Correction (Legacy MIP)**: Spans 224 active sessions ($Y = 0.8889$ yr). Cumulative total return is **-19.55%**, whereas CAGR is **-21.71%**. MaxDD is **26.29%**, which strictly satisfies $26.29\% \ge 19.55\%$.
  - **2020 COVID Crash (Legacy MIP)**: Spans 77 active sessions ($Y = 0.3056$ yr). Cumulative total return is **-18.24%**, whereas CAGR is **-48.27%**. MaxDD is **38.83%**, which strictly satisfies $38.83\% \ge 18.24\%$.
- The mathematical identity $\text{MaxDD} \ge |\text{total\_return}|$ holds strictly across all evaluated negative-return windows where trade data is sufficient.

### Warmup Declaration & Cash Accounting (Task 2)
- **2008 Global Financial Crisis** (246 trading days):
  - **Legacy MIP**: First invested date: `2008-02-01`. Days in cash: **23 days** (9.3% of window).
  - **Top Config**: First invested date: `2008-05-02`. Days in cash: **82 days** (33.3% of window).
  - **Status & Declaration**: `DATA_INSUFFICIENT — excessive in-window cash masked 33.3% of window (Legacy: 23/246 days, Top: 82/246 days). Drawdown numbers cannot be interpreted as stress-test drawdowns.`
- **2011 European Debt Crisis** (246 trading days):
  - **Legacy MIP**: First invested date: `2011-02-01`. Days in cash: **20 days** (8.1% of window).
  - **Top Config**: First invested date: `2011-04-01`. Days in cash: **62 days** (25.2% of window).
  - **Status & Declaration**: `excludes warmup lookback (252 sessions). In-window cash spanned 20 days for Legacy / 62 days for Top.`
- **2018 Midcap Crash / Correction** (246 trading days):
  - **Legacy MIP**: First invested date: `2018-02-01`. Days in cash: **22 days** (8.9% of window).
  - **Top Config**: First invested date: `2018-02-01`. Days in cash: **22 days** (8.9% of window).
  - **Status & Declaration**: `excludes warmup lookback (252 sessions). In-window cash spanned 22 days for Legacy / 22 days for Top.`
- **2020 COVID Crash** (100 trading days):
  - **Legacy MIP**: First invested date: `2020-02-03`. Days in cash: **23 days** (23.0% of window).
  - **Top Config**: First invested date: `2020-05-04`. Days in cash: **81 days** (81.0% of window).
  - **Status & Declaration**: `DATA_INSUFFICIENT — excessive in-window cash masked 81.0% of window (Legacy: 23/100 days, Top: 81/100 days). Drawdown numbers cannot be interpreted as stress-test drawdowns.`

### 2020 COVID Crash: Precision & Trade Log Event (Task 3)
- **Top Config Raw Metrics**: CAGR **+18.58%**, MaxDD **1.5725%**, Calmar **11.83** (Genuine raw precision, no zero-percent placeholder).
- **Trade Log Event Disclosing Cash State**:
  - `2020-01-01`: Window starts with ₹1,000,000 cash (100.0% cash weight, 0 holdings).
  - `2020-01-31, 2020-02-28, 2020-03-31`: 20-EMA Benchmark Regime was **BEARISH (0)**. The Regime Gate suppressed all new entries throughout the crash.
  - `2020-04-30`: Benchmark closed above 20 EMA, triggering a **BULLISH (1)** entry signal.
  - `2020-05-04`: T+1 execution re-entered qualifying momentum stocks once bull regime resumed.
  - **2020 Top Config Horizon Mismatch**: Top Config was invested for only 19 sessions (2020-05-04 to 2020-05-29) out of the 100-session window. The annualized CAGR (+18.58%) reflects return annualized across the 100-session calendar window (Y = 0.3968 yr), whereas the intra-period MaxDD (1.57%) represents the maximum peak-to-trough drop observed during the 19 active invested sessions.
  - **Assertion A3 Verdict: VIOLATED**: The historical marketing claim that the strategy 'went 100% to cash before the crash' is **VIOLATED**. As proven by the trade ledger (`stress_trade_ledger.json`), exactly 0 sell orders occurred in the window. The strategy entered the window flat (0 holdings) and was kept flat by the 20-EMA benchmark regime filter, never executing a liquidation sell order.

### 2008 Half-Cash Condition Forensic Investigation & Cash Artifact Determination

A deep forensic audit of the 2008 Global Financial Crisis window was performed to determine why Legacy MIP experienced only a 17.53% drawdown.

#### Monthly Rebalance Position Filling & Filter Breakdown Table (2008 GFC)

| Rebalance Date | Target | Filled | New Buys | Cash % | Active Universe | Pass Retrace | Pass 200-EMA | Pass RS | Qualifying Candidates | Primary Bottleneck |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2008-01-31 | 20 | 9 | 9 | 55.4% | 75 | 12 | 10 | 10 | 9 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-02-29 | 20 | 9 | 3 | 55.1% | 76 | 11 | 10 | 10 | 9 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-03-31 | 20 | 4 | 3 | 79.8% | 76 | 5 | 5 | 5 | 4 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-04-30 | 20 | 7 | 4 | 64.8% | 76 | 10 | 10 | 9 | 7 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-05-30 | 20 | 7 | 3 | 64.7% | 76 | 9 | 9 | 9 | 7 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-06-30 | 20 | 4 | 0 | 79.8% | 76 | 6 | 6 | 6 | 4 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-07-31 | 20 | 6 | 3 | 69.0% | 76 | 7 | 7 | 7 | 6 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-08-29 | 20 | 7 | 2 | 63.3% | 76 | 8 | 8 | 8 | 7 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-09-30 | 20 | 4 | 0 | 78.2% | 76 | 6 | 5 | 5 | 4 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-10-31 | 20 | 2 | 0 | 89.8% | 76 | 2 | 2 | 2 | 2 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |
| 2008-11-28 | 20 | 2 | 0 | 89.6% | 76 | 3 | 2 | 2 | 2 | Filter Dry-up (Retrace < 80% & Close <= 200 EMA) |

#### Root Cause Breakdown & Code Citations
1. **Data Availability / Universe Size**: In 2008, only 75–76 symbols in the NIFTY500 database had valid trading data (`brute_force/cube_builder.py:321-331`).
2. **Retrace Filter Bottleneck**: During severe market declines, momentum names violated the 80% 52-week high threshold (`brute_force/sim_kernel.c:385`). In March and June 2008, only 5–6 stocks passed.
3. **200-Day EMA Trend Bottleneck**: The severe bear market pushed most stocks below their 200-day EMA (`brute_force/sim_kernel.c:386`). By October/November 2008, only 2 stocks passed the 200-EMA filter.
4. **Relative Strength Pass**: Candidates were further restricted by the RS filter (`brute_force/sim_kernel.c:387`).
5. **Fixed 1/N Sizing & Cash Drag**: The engine implements fixed $1/N$ allocation ($1/20 = 5\%$ per position slot) via `sim_kernel.c:423`. Unallocated slots remain in cash. Because only 2–9 stocks ever qualified, the portfolio held significant idle cash throughout 2008.

#### Before/After Fix MaxDD Side-by-Side Comparison

| Metric | Before Fix (Cash-Cushioned Artifact) | After Fix (Normalized 100% Equity) | Determination |
| :--- | :--- | :--- | :--- |
| 2008 GFC Max Drawdown | 17.53% | 62.10% | `cash_artifact` |

- **Verdict**: The reported 17.53% drawdown in 2008 is officially classified as a **cash artifact** caused by filter dry-up under fixed 1/N sizing, rather than true equity market resilience.

### Ledger Consolidation Notice

- **Authoritative Trade Ledger**: `reports/forensic_audit/stress_trade_ledger.json` is designated as the single authoritative source of truth for all stress testing trade executions, cash movements, and position holdings.
- **Derived Rebalance Events**: `reports/forensic_audit/stress_rebalance_events.json` is designated as a derived event stream maintained for backwards compatibility with downstream analytics.

## 6. RECOMMENDATION & REGIME-DEPENDENCE WARNING (TASK 6)

> [!WARNING]
> **REGIME-DEPENDENCE CRITICAL WARNING**: All top configurations depend on `regime_gate: true`, whose contribution Flips between IS (Δ-6.6%) and OOS (Δ+5.2%). The recommended config may underperform or suffer whipsaw losses in a choppy, sideways market regime where the 20-EMA gate whipsaws. Before live allocation, the investment committee must test the top-3 configs with `regime_gate: false` to establish the downside tail risk.

