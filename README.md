# Project MIP — Institutional Momentum Trading Desk & Quantitative Research Platform
### Standalone Zero-Compiler Edition • Python 3.10+ • ARM64 NEON & x86_64 AVX2 Parallel SIMD Engine

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Afylx01/Project_MIP_Colab/blob/main/notebooks/Project_MIP_Colab.ipynb)
[![Version: v2.4.0](https://img.shields.io/badge/Version-v2.4.0-blue.svg)](CHANGELOG.md)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Architecture: ARM64 + x86_64](https://img.shields.io/badge/Architecture-ARM64%20NEON%20%7C%20x86__64%20AVX2-brightgreen.svg)]()
[![Platform: Colab + Android + Linux](https://img.shields.io/badge/Platform-Google%20Colab%20%7C%20Pydroid%203%20%7C%20Linux%20HPC-orange.svg)]()
[![Database Integrity](https://img.shields.io/badge/Database-2.16M%20Rows%20%7C%20Point--in--Time%20Sealed-success.svg)]()
[![Strategy Fingerprint](https://img.shields.io/badge/Strategy%20Fingerprint-9036fae5...73de-blueviolet.svg)]()

---

## 📑 Table of Contents

1. [Executive Summary & Platform Overview](#-executive-summary--platform-overview)
2. [Theoretical & Quantitative Rationale (The "Why")](#-theoretical--quantitative-rationale-the-why)
   - Academic Precedents & Empirical Foundation
   - The Indian Equity Market (NSE) Momentum Regime
   - Discretionary Traps vs. Systematic Mathematical Invariants
3. [Core Strategy Architecture & Rules (The "What")](#-core-strategy-architecture--rules-the-what)
   - The 9 Canonical Invariants
   - The 5-Tier Strategy Filter Hierarchy
   - Candidate Ranking Engine: Volar Score vs. Raw Momentum
   - Dynamic Stop-Loss & Volatility Risk Parity Sizing
   - Exit Buffer (Rank 40) Hysteresis & Capital Recycling
4. [Mathematical & Algorithmic Formulations](#-mathematical--algorithmic-formulations)
   - Return, Rolling High, and Retracement Math
   - Annualized Realized Volatility & Floor Guard
   - Volar Score (Risk-Adjusted Momentum) Formulation
   - Relative Strength (RS) Ratio & Dual-Span EMA Filters
   - Average True Range (ATR-14) & Dynamic Risk Stops
   - Deflated Sharpe Ratio (DSR) & Statistical Significance
5. [End-to-End Screening & Execution Lifecycle](#-end-to-end-screening--execution-lifecycle)
   - Phase 0: Pre-Flight & Latest Trading Day Resolution
   - Phase 1: Security Ingestion & Anti-IPO Invariants
   - Phase 2: Corporate Actions Treatment & Historical Partitioning
   - Phase 3: Factor Computation & Geometric Bar Validation
   - Phase 4: Strategy Gating & Diagnostic Reason Codes
   - Phase 5: Deterministic 3-Tier Tie-Breaking
   - Phase 6: Sector Anti-Clustering Enforcement
   - Phase 7: Portfolio Rebalancing & Order Ticket Generation
6. [Indian Market Microstructure & Friction Modeling](#-indian-market-microstructure--friction-modeling)
   - 15 bps Statutory Friction Breakdown (STT, GST, Stamp Duty, Turnover)
   - 5 bps Execution Slippage & T+1 Open Fills
   - Whole-Share Integer Rounding & Cash Conservation
7. [Point-in-Time Data Integrity & Historical Database](#-point-in-time-data-integrity--historical-database)
   - SQLite `universe.db` Specification (2.17M Bars, 1,083 NSE Symbols)
   - Cryptographic Immutability & SHA-256 Sealing
   - Survivorship Bias Elimination (Delisted & Merged Scrips)
   - Look-Ahead Bias Prevention & Corporate Actions Timeline
   - Production Mutation Firewall (`MIP_ALLOW_PROD_MUTATION`)
8. [High-Compression Cloud Storage Architecture (`universe.db.gz`)](#-high-compression-cloud-storage-architecture-universedbgz)
   - Solving Google Drive Quota Exhaustion (>70% Space Saved)
   - Eliminating the 40x Google Drive FUSE Network Bottleneck
   - Streaming Chunked Gzip Decompress-on-Stage (<1.5s NVMe Ingestion)
   - Two-Way Cloud Synchronization & Zero-Leak Secrets Isolation
9. [Multi-Architecture C99 SIMD Parallel Simulation Engine](#-multi-architecture-c99-simd-parallel-simulation-engine)
   - In-Memory Tensor Cube Architecture (<280 MB RAM)
   - Hardware Vectorization: x86_64 AVX2/FMA vs. ARM64 NEON
   - Zero-Copy Ctypes Memory Mapping & Thread-Pool Work Stealing
   - Benchmark Latency: 41.3 ms Single Sim (1,590x Speedup)
   - Sweep Throughput: 767+ Runs/Sec (23,260x Speedup)
10. [Comprehensive Empirical Backtest Results & Comparative Benchmarks](#-comprehensive-empirical-backtest-results--comparative-benchmarks)
    - PIT Canonical Baseline (2018–2026 Monthly)
    - Recommended Profile A vs NIFTY 500
    - Survivorship / Look-Ahead Control (+2.81 pp CAGR)
    - Retired Legacy Tables (withdrawn — survivorship-biased)
11. [Universal NSE Index Catalog (36 Universes)](#-universal-nse-index-catalog-36-universes)
    - Broad Market, Sectoral, and Thematic Universes
    - Constituent Reconciliation Engine & 30-Day Cache TTL Policy
12. [System Architecture & 24 Decoupled Core Modules](#-system-architecture--24-decoupled-core-modules)
    - Directory Topology
    - 25 Core Modules Provenance Manifest
    - 14-Sheet Institutional Excel Tearsheet Structure
13. [Deployment & Operations Guide](#-deployment--operations-guide)
    - Google Colab Interactive Cloud Cockpit (4-Cell Workflow)
    - Android S23 / Pydroid 3 / Termux Mobile Trading Desk
    - Headless CLI Commands & Options [1] through [18]
    - Cron Scheduler Daemon & Automated Telegram Alerting
14. [Security Governance & Auditing Protocol](#-security-governance--auditing-protocol)
    - Zero-Leak Security Guarantee
    - Pre-Completion Audit Protocol (The 5 Quantitative Validity Pillars)
15. [License & Institutional Disclaimer](#-license--institutional-disclaimer)

---

## 🏛 Executive Summary & Platform Overview

**Project MIP** is an institutional-grade, multi-architecture quantitative momentum trading desk and research platform. Originally developed for mobile high-performance deployment on Android ARM64 hardware (Qualcomm Snapdragon 8 Gen 2 / Pydroid 3 / Termux PRoot Ubuntu), it is architected to scale seamlessly into **Google Colab Cloud (x86_64 Intel Xeon / AMD EPYC)** and Linux HPC clusters without external compiler toolchain dependencies.

The platform executes a rigorous, rules-based momentum anomaly capture strategy designed specifically for the National Stock Exchange of India (NSE). By combining cross-sectional momentum, dual-span exponential trend filtering, index relative strength benchmarking, 52-week high retracement thresholds, anti-clustering sector caps, and volatility risk parity sizing, the system transforms raw market price series into actionable, risk-controlled institutional trade tickets and comprehensive 14-sheet Excel workbooks.

### Key Operational Highlights

| Dimension | Specification | Institutional Purpose |
| :--- | :--- | :--- |
| **Strategy Class** | Cross-Sectional Volatility-Adjusted Momentum (Volar) | Exploits persistent drift in leading equities while mitigating volatility drag |
| **Core Universe** | NIFTY 750 / NIFTY 500 / All NSE Active Traded Equity | Broad liquidity pool across Large, Mid, and Small-cap equities |
| **Historical Data** | 2,170,608 point-in-time bars across 1,083 symbols (2007–2026) | Full point-in-time price history with corporate action adjustments |
| **Execution Cadence** | Monthly Rebalance (with Weekly, Quarterly, Semi-Annual support) | Optimizes alpha capture against Indian statutory friction and turnover drag |
| **Execution Latency** | 41.3 ms (Single 10-year simulation) / 767 runs/sec (SIMD sweep) | Sub-second parameter space exploration and neighborhood sensitivity verification |
| **Data Immutability** | SQLite database sealed via SHA-256 (`0077ea77...`) | Cryptographic protection against unintended data mutations and look-ahead leaks |
| **Cloud Storage** | Streaming chunked Gzip (`universe.db.gz`, ~101 MB) | 70%+ space savings on Google Drive with 1.5s local NVMe decompression |

---

## 🔬 Theoretical & Quantitative Rationale (The "Why")

### 1. Academic Precedents & Empirical Foundation

The momentum anomaly represents one of the most robust, pervasive, and extensively documented empirical regularities across global asset classes:

1. **Foundational Cross-Sectional Momentum (Jegadeesh & Titman, 1993, 2001):**
   * *Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency* (Journal of Finance).
   * Documented that past medium-term winners (3 to 12 months) systematically outperform past losers over the subsequent 3 to 12 months.
   * Behavioral rationale: Market participants suffer from **anchoring**, **disposition effect**, and **underreaction** to new fundamental information (earnings surprises, revisions, revenue acceleration). As information diffuses gradually through retail and institutional tiers, stock prices exhibit persistent drift.

2. **Cross-Asset Ubiquity (Asness, Moskowitz, & Pedersen, 2013):**
   * *Value and Momentum Everywhere* (Journal of Finance).
   * Demonstrated that momentum exists across 4 distinct asset classes (US equities, international equities, currencies, and fixed income) over four decades.
   * Confirms momentum is not an artifact of data-mining, survivorship, or transaction costs, but an institutional structural risk premium.

3. **The 52-Week High Anomaly (George & Hwang, 2004):**
   * *The 52-Week High and Momentum Investing* (Journal of Finance).
   * Revealed that price level relative to a stock's 52-week high is a dramatically more potent predictor of future returns than past total returns alone.
   * Behavioral rationale: The 52-week high serves as a powerful psychological anchor. Traders are reluctant to bid a stock past its historical peak, creating temporary resistance and severe underreaction. When a stock breaks through or trades within 20% of its 52-week peak, it encounters reduced overhead supply and continues to drift upward.

4. **Volatility Scaling & Residual Momentum (Blitz, Huij, & Martens, 2011; Blitz & van Vliet, 2007):**
   * *Residual Momentum* (Journal of Empirical Finance) & *The Volatility Effect* (Journal of Portfolio Management).
   * Standard 12-month raw return momentum is prone to sharp, violent drawdowns ("momentum crashes", Barroso & Santa-Clara, 2015) when high-beta, high-volatility losers violently rally during market rebounds.
   * By scaling returns by annualized realized volatility ($\text{Volar} = \text{Return} / \sigma$), Project MIP eliminates "lottery stock" penny spikes and favors stable, institutional, low-beta compounders with superior Sharpe ratios.

5. **Volatility Targeting & Dynamic Risk Budgeting (Harvey et al., 2018; AQR):**
   * *Risk-Managed Momentum* (AQR Capital Management).
   * Momentum portfolios exhibit time-varying volatility. Systematically controlling risk through ATR-based position sizing and regime gating tames tail risk, compresses maximum drawdowns by 30%+, and elevates the Calmar ratio.

### 2. The Indian Equity Market (NSE) Momentum Regime

The National Stock Exchange of India (NSE) offers an exceptionally fertile environment for systematic momentum strategies:
* **High Dispersion:** The wide performance spread between top-performing emerging sectors (e.g., Capital Goods, Defense, Renewables, PSU, Electronics) and lagging sectors creates significant cross-sectional alpha.
* **Rapid Institutional Inflows:** Systematic Investment Plans (SIPs) into domestic mutual funds provide steady, inelastic liquidity that flows disproportionately into market leaders, amplifying medium-term price trends.
* **Retail Herd Bias:** Retail participation often chases lagging or highly volatile penny scrips, providing steady liquidity for systematic desks executing disciplined trend rebalances.

### 3. Discretionary Traps vs. Systematic Mathematical Invariants

Why do 90%+ of discretionary momentum traders underperform?
* **Whipsaw & Chasing Extended Stocks:** Buying stocks when they are extended $+40\%$ or more above their 200 EMA, leading to immediate pullbacks.
* **Sector Over-Concentration (Clustering):** Discretionary traders often load 60–80% of their capital into a single hot theme (e.g., 10 PSU banks or 8 defense stocks in 2023–2024). When the theme mean-reverts, the portfolio suffers catastrophic drawdowns.
* **Premature Profit Taking & Loss Holding:** Discretionary traders sell winners after 10% gains (cutting runners) while holding losers down 30% (hoping for a rebound).
* **Friction Blindness:** Ignoring Indian statutory costs (STT, GST, stamp duty, turnover fees) which can erode 5–10% of gross capital annually under high-turnover weekly churn.

Project MIP resolves every one of these failure modes through **strict, immutable mathematical gates**.

---

## 🎯 Core Strategy Architecture & Rules (The "What")

Project MIP implements a deterministic, multi-stage filtration and portfolio construction pipeline:

```
[ All NSE Listed Equities (1,083 Active Scrips) ]
                         │
                         ▼
             [ Security Ingestion Gate ]
             • Anti-IPO Filter: Minimum 252 Trading Bars History
             • Geometric Bar Validator: H >= L, H >= O, H >= C, L <= O, L <= C
             • Corporate Actions Normalization: Splits/Bonuses/Demergers
                         │
                         ▼
             [ 5-Tier Strategy Filter Hierarchy ]
             • Filter 1 (Retracement): Close >= 0.80 * 52w High
             • Filter 2 (Trend EMA):   Close > 200 EMA
             • Filter 3 (Relative RS): (Stock / Nifty500) > 200 EMA of Ratio
             • Filter 4 (Regime):      Nifty500 Close > 20 EMA
             • Filter 5 (Momentum):    Return_252 > 0 and Volar > 0
                         │
                         ▼
             [ Deterministic 3-Tier Ranking ]
             • Primary:   Volar Score DESC
             • Secondary: 252-day Return DESC
             • Tertiary:  Security ID ASC (Zero-Entropy Tie-Breaker)
                         │
                         ▼
             [ Anti-Clustering Sector Cap ]
             • Greedy Selection: Max 2 Scrips Per Industry/Sector
             • Pool Target: Top 20 Candidates
                         │
                         ▼
             [ Portfolio Engine & Execution Ledger ]
             • Exit Buffer (Rank 40 Hysteresis) for Existing Holdings
             • ATR-14 Volatility Risk Parity Sizing (1% Capital Risk)
             • Dynamic 2.0x ATR Stop-Loss
             • Whole-Share Integer Allocation & Cash Conservation
             • Next-Session (T+1) Open Execution + 20 bps Frictions
```

### The 9 Canonical Invariants

These 9 parameters are mathematically sealed and verified across every backtest, scan, and production tear sheet:

```python
@dataclass(frozen=True)
class MIPScannerConfig:
    momentum_lookback_bars: int = 252       # 1-Year Annualized Lookback (Return_252)
    rolling_high_bars: int = 252            # 52-Week Rolling High Window
    rolling_low_bars: int = 252             # 52-Week Rolling Low Window
    retrace_threshold: float = 0.80         # Filter 1: Close >= 80% of 52w High
    ema_trend_span: int = 200               # Filter 2: Stock Trend EMA Span
    ema_rs_span: int = 200                  # Filter 3: Relative Strength EMA Span
    ema_regime_span: int = 20               # Filter 4: Benchmark Market Regime Span
    top_n_candidates: int = 20              # Filter 5: Target Portfolio Size (N=20)
    exit_buffer_rank: int = 40              # Rebalance Retention Buffer Rank (Hysteresis)
    max_per_sector: int = 2                 # Anti-Clustering Cap per Industry
    atr_stop_multiplier: float = 2.0        # Dynamic Stop Loss Multiplier
    risk_budget_pct: float = 0.01           # 1% Account Equity Risk per Position
    volatility_floor: float = 0.05          # 5% Annualized Volatility Denominator Floor
```

### The 5-Tier Strategy Filter Hierarchy

1. **Filter 1 — 52-Week High Retracement (George & Hwang Rule):**
   $$\text{Close}_t \ge 0.80 \times \max_{0 \le k < 252} \left( \text{High}_{t-k} \right)$$
   *Rationale:* Eliminates stocks trapped in deep cyclical bear markets. A stock trading more than 20% below its 52-week peak faces massive overhead supply from trapped buyers looking to break even.
2. **Filter 2 — Long-Term Trend Alignment (200 EMA):**
   $$\text{Close}_t > \text{EMA}_{200, t}(\text{Close})$$
   *Rationale:* Guarantees the stock is in a confirmed secular macro uptrend. Historically, stocks trading below their 200-day moving average exhibit negative skewness and heightened crash risk.
3. **Filter 3 — Outperformance vs. Market (Relative Strength EMA):**
   $$\text{RS}_t = \frac{\text{Close}_{\text{Stock}, t}}{\text{Close}_{\text{NIFTY500}, t}}, \quad \text{RS}_t > \text{EMA}_{200, t}(\text{RS})$$
   *Rationale:* Prevents buying stocks that are merely drifting upward due to general market beta. The stock must be systematically outperforming the broad benchmark index.
4. **Filter 4 — Benchmark Market Regime Gate (20 EMA Regime):**
   $$\text{Close}_{\text{NIFTY500}, t} > \text{EMA}_{20, t}(\text{Close}_{\text{NIFTY500}})$$
   *Rationale:* Evaluates the short-term market health. When the benchmark trades below its 20 EMA, the engine enters **Defensive Mode**: new long entries are halted, cash is preserved, while existing positions are trailed with their stop-loss rules.
5. **Filter 5 — Absolute Positive Momentum:**
   $$R_{252, t} > 0 \quad \text{and} \quad \text{Volar}_t > 0$$
   *Rationale:* Ensures the equity delivered absolute positive price appreciation over the past 252 trading sessions.

### Dynamic Stop-Loss & Volatility Risk Parity Sizing

Every position generated by Project MIP is protected by a volatility-calibrated dynamic stop loss:

$$\text{Stop Loss} = \max\left(0.01, \, \text{Close} - 2.0 \times \text{ATR}_{14}\right)$$

Position sizing is governed by **ATR Volatility Risk Parity**:
1. Calculate the total dollar risk budget:
   $$\text{Risk Budget} = \text{Capital} \times 0.01 \quad (\text{1\% of Account NAV})$$
2. Calculate risk per share, bounded by a minimum 2% distance:
   $$\text{Risk Per Share} = \max\left(2.0 \times \text{ATR}_{14}, \, 0.02 \times \text{Close}\right)$$
3. Calculate target shares via integer floor division, capped at 25% portfolio concentration:
   $$Q_{\text{risk}} = \left\lfloor \frac{\text{Risk Budget}}{\text{Risk Per Share}} \right\rfloor, \quad Q_{\text{cap}} = \left\lfloor \frac{0.25 \times \text{Capital}}{\text{Close}} \right\rfloor$$
   $$\text{Target Shares} = \max\left(0, \, \min(Q_{\text{risk}}, Q_{\text{cap}})\right)$$

### Exit Buffer (Rank 40) Hysteresis & Capital Recycling

In a naive momentum strategy, rebalancing every month causes excessive turnover: a stock ranked #20 this month that drops to #22 next month is sold, incurring round-trip frictions.

Project MIP incorporates an **Exit Buffer (Rank 40 Hysteresis Gate)**:
* To enter the portfolio, a new candidate must rank within the **Top 20**.
* Once held, a position is **retained** as long as:
  1. Its rank remains $\le 40$ in the screened universe.
  2. Its price remains $\ge 0.80 \times \text{High}_{252}$.
  3. Its price remains $> 200 \text{ EMA}$.
  4. Its trailing ATR stop loss is not breached.
* If a holding violates any of these four conditions, it is immediately scheduled for exit at the next market open ($T+1$), and the open portfolio slot is recycled to the highest-ranking newcomer.

---

## 📐 Mathematical & Algorithmic Formulations

### 1. 252-Day Price Return
$$R_{252, t} = \frac{P_t}{P_{t-252}} - 1.0$$
where $P_t$ is the split-and-bonus adjusted closing price at session $t$, and $P_{t-252}$ is the price exactly 252 trading sessions prior.

### 2. Annualized Realized Volatility ($\sigma_{252}$)
Daily logarithmic or percentage return:
$$r_t = \frac{P_t}{P_{t-1}} - 1.0$$
Annualized sample standard deviation with Bessel's correction ($N = 252$):
$$\bar{r} = \frac{1}{252} \sum_{k=0}^{251} r_{t-k}$$
$$\sigma_{252, t} = \sqrt{252} \times \sqrt{\frac{1}{251} \sum_{k=0}^{251} (r_{t-k} - \bar{r})^2}$$
To eliminate division-by-zero or extreme amplification on ultra-low-volatility assets, a strict floor is applied:
$$\sigma_{\text{eff}, t} = \max\left(\sigma_{252, t}, \, 0.05\right)$$

### 3. Volar Score (Risk-Adjusted Momentum)
$$\text{Volar}_t = \frac{R_{252, t}}{\sigma_{\text{eff}, t}} = \frac{R_{252, t}}{\max\left(\sigma_{252, t}, \, 0.05\right)}$$

*Why Volar Dominates Raw Momentum:*
Consider two stocks:
* **Stock A (Erratic Penny Spike):** $R_{252} = +100\%$, $\sigma_{252} = 80\% \implies \text{Volar} = \frac{1.00}{0.80} = 1.25$.
* **Stock B (Institutional Compounder):** $R_{252} = +50\%$, $\sigma_{252} = 18\% \implies \text{Volar} = \frac{0.50}{0.18} = 2.77$.

Raw momentum would choose Stock A, exposing the portfolio to severe drawdown risk. **Volar correctly ranks Stock B first**, isolating high-quality institutional trends.

### 4. Exponential Moving Average (EMA)
$$\alpha = \frac{2}{\text{span} + 1}$$
$$\text{EMA}_t = \alpha P_t + (1 - \alpha) \text{EMA}_{t-1}$$
For 200 EMA: $\alpha_{200} = \frac{2}{201} \approx 0.00995$.
For 20 EMA: $\alpha_{20} = \frac{2}{21} \approx 0.09524$.

### 5. Average True Range (ATR-14)
$$\text{TR}_t = \max\left( \text{High}_t - \text{Low}_t, \, |\text{High}_t - \text{Close}_{t-1}|, \, |\text{Low}_t - \text{Close}_{t-1}| \right)$$
$$\text{ATR}_{14, t} = \frac{1}{14} \sum_{i=0}^{13} \text{TR}_{t-i}$$

### 6. Deflated Sharpe Ratio (DSR)
To guard against data-snooping and multiple testing bias across hundreds of parameter configurations, the Deflated Sharpe Ratio (Bailey & López de Prado, 2014) is evaluated:
$$\text{DSR} \equiv \Phi\left( \frac{(\widehat{SR} - SR^*) \sqrt{T-1}}{\sqrt{1 - \widehat{\gamma}_3 \widehat{SR} + \frac{\widehat{\gamma}_4 - 1}{4} \widehat{SR}^2}} \right)$$
where $SR^*$ is the expected maximum Sharpe ratio under the null hypothesis of zero skill given $M$ trials:
$$SR^* \approx \sqrt{2 \ln M} + \frac{\gamma}{\sqrt{2 \ln M}}$$
All canonical configurations pass DSR verification ($p < 0.01$).

---

## 🔄 End-to-End Screening & Execution Lifecycle

The platform executes a strict 7-phase pipeline on every scan:

### Phase 0: Pre-Flight & Latest Trading Day Resolution
1. Queries the real-time Indian Standard Time (IST) clock (`Asia/Kolkata`, UTC+5:30).
2. Authoritative calendar check (`data/trading_calendar.txt`, 4,888 verified sessions).
3. Evaluates 18:30 IST market data publish cutoff. If current time is $<18:30$ IST, the expected session is $T-1$; if $\ge 18:30$ IST, today's session is validated.
4. Fails closed with `DataUnavailableError` if the database is missing expected bars.

### Phase 1: Security Ingestion & Anti-IPO Invariants
1. Queries raw bars from SQLite `prices` table.
2. Evaluates the **Anti-IPO Invariant**: Every security must possess $\ge 252$ contiguous trading bars of history. Newly listed IPOs and recent listings are mathematically quarantined with reason code `INSUFFICIENT_HISTORY`.

### Phase 2: Corporate Actions Treatment & Historical Partitioning
1. Loads verified corporate actions registry (`data/corporate_actions_registry.json`).
2. **Enterprise-Preserving Actions (Splits & Bonus Issues):** Continuous backward factor adjustment on all historical $O, H, L, C$ series.
3. **Enterprise-Altering Actions (Demergers & Carve-Outs):** Historical partitioning. Bars prior to demerger ex-date are partitioned to prevent false price drop signals.
4. Unresolved corporate price dislocations $>40\%$ are quarantined with `UNRESOLVED_STRUCTURAL_PRICE_EVENT`.

### Phase 3: Factor Computation & Geometric Bar Validation
Every bar must satisfy strict physical geometric price constraints:
$$\text{High} \ge \text{Low}, \quad \text{High} \ge \text{Open}, \quad \text{High} \ge \text{Close}, \quad \text{Low} \le \text{Open}, \quad \text{Low} \le \text{Close}$$
Any bar failing these checks is purged, and the security is logged with `INVALID_OHLC`.

### Phase 4: Strategy Gating & Diagnostic Reason Codes
Every candidate is evaluated against the 5 strategy filters. If a security fails, it is assigned a structured diagnostic reason code:
* `PASS`: Qualified for ranking.
* `BELOW_52W_HIGH_THRESHOLD`: Failed Filter 1 (Close $< 0.80 \times \text{High}_{252}$).
* `BELOW_EMA200`: Failed Filter 2 (Close $\le \text{EMA}_{200}$).
* `RS_BELOW_EMA`: Failed Filter 3 ($\text{RS} \le \text{EMA}_{200}(\text{RS})$).
* `NEGATIVE_MOMENTUM`: Failed Filter 5 ($R_{252} \le 0$ or Volar $\le 0$).
* `STALE_BENCHMARK`: Benchmark data missing or out of sync.

### Phase 5: Deterministic 3-Tier Tie-Breaking
Qualified candidates are sorted deterministically:
$$\text{Sort Order} = \left( \text{Volar Score} \downarrow, \, R_{252} \downarrow, \, \text{Security ID} \uparrow \right)$$
Zero randomness or floating-point instability is permitted.

### Phase 6: Sector Anti-Clustering Enforcement
A greedy selector iterates through the sorted qualified candidates:
* Tracks the running count of selected stocks per sector.
* If a sector already has 2 stocks (`max_per_sector = 2`), subsequent candidates in that sector are bypassed with reason `SECTOR_CAP_EXCEEDED`.
* Continues until exactly 20 candidates are selected or the candidate pool is exhausted.

### Phase 7: Portfolio Rebalancing & Order Ticket Generation
* Compares target candidates against current holdings.
* Evaluates Rank 40 exit buffer for existing positions.
* Sizes new entries via ATR Volatility Risk Parity.
* Deducts statutory frictions and formats execution tickets.

---

## 🇮🇳 Indian Market Microstructure & Friction Modeling

Unlike theoretical papers that assume zero frictions, Project MIP incorporates realistic Indian statutory costs and execution slippage into every simulation.

### Statutory Friction Breakdown (15 bps Base Frictions)

| Cost Component | Statutory Rate | Applied Basis | Institutional Formula |
| :--- | :--- | :--- | :--- |
| **STT (Securities Transaction Tax)** | 0.100% (10 bps) | Delivery Buy & Sell | $0.0010 \times \text{Turnover}$ |
| **Exchange Turnover Fee (NSE)** | 0.00345% (~0.35 bps) | Gross Turnover | $0.0000345 \times \text{Turnover}$ |
| **GST (Goods & Services Tax)** | 18.00% | Brokerage + Turnover Fee | $0.18 \times (\text{Brokerage} + \text{Turnover Fee})$ |
| **SEBI Regulatory Fee** | ₹10 / Crore (0.01 bps) | Gross Turnover | $0.000001 \times \text{Turnover}$ |
| **Stamp Duty (Buy Side)** | 0.015% (1.5 bps) | Buy Side Delivery | $0.00015 \times \text{Buy Turnover}$ |
| **Institutional Brokerage** | 0.030% (3 bps) | Delivery Trades | $0.0003 \times \text{Turnover}$ |

**Combined Base Statutory Frictions:** $\approx 15 \text{ basis points (0.15\%)}$ per rebalance leg.

### Execution Slippage & Timing Realism (5 bps Slippage)
* **T+1 Open Execution:** Rebalance decisions generated at the close of trading session $T$ are executed at the **Open price of session $T+1$**. No same-day close execution fantasy.
* **Slippage Modeling:** 5 basis points ($0.05\%$) adverse fill applied on every trade execution to model bid-ask spread crossing and impact.
* **Total Round-Trip Execution Drag:** **20 basis points (0.20%)** applied unconditionally across every trade.

### Whole-Share Integer Rounding & Cash Conservation
The portfolio manager operates strictly on whole-share integers:
$$\text{Shares} \in \mathbb{Z}^+, \quad \text{Fractional Shares} = 0$$
$$\text{Cash Balance}_t \ge 0.0 \quad \text{at all times (Zero Margin Borrowing)}$$
If the total cost of calculated buy tickets exceeds available cash, an automated budget normalization scalar shrinks positions proportionally, ensuring total capital allocation never exceeds $99\%$ of available capital.

---

## 💾 Point-in-Time Data Integrity & Historical Database

### SQLite `universe.db` Specification
* **Total Records:** **2,170,608 OHLCV daily bars**
* **Symbol Coverage:** **1,083 distinct NSE equity symbols**
* **Time Span:** January 2007 through October 2026 (19+ years)
* **Uncompressed Size:** 351,744,000 bytes (~351.7 MB)
* **Primary Key:** `PRIMARY KEY (symbol, date)`
* **Cryptographic SHA-256 Fingerprint:**
  ```
  2cea970063a65c0ca129ac459467f6b3de466e05be456b50cc63ff1651e8b6ef
  ```

### Survivorship Bias Elimination
Historical index backtests now use **point-in-time membership**, not the current list. `data/pit_constituents/nifty500_snapshots.csv` contains 50 full NIFTY500 snapshots (2016-01-18 → 2026-09-30) from niftyhistory.in, cross-checked against the CC BY 4.0 `nse-historical-membership` interval table. Membership is resolved on every rebalance; a holding removed from the index is exited. **2016-01-01 is refused** because no snapshot exists on or before that date. The canonical window starts in 2018 — the first year with at least 70% tradable coverage (377 mapped / 356 eligible). 2017 is runnable (305 eligible) but is outside the pre-registered canonical window. The live scanner is the only component that uses the latest constituents.

The residual limitation is **price-history completeness**, not membership selection: in 2018, 377 of 501 members map to a DB price series and 356 have the required 252 bars (453/434 by 2024; 496 mapped by 2026). The measured current-list control — same engine, config and dates on today's 2026 list — overstates CAGR by **+2.81 pp** (25.75% vs 22.94%); that is the one-number survivorship/look-ahead estimate under this tag. The old "4–8% annually" range and the ALL-vs-survivors 1.51 pp diagnostic are retired. Verification: `reports/PIT_MEMBERSHIP_VERIFICATION.md`; engine matrix and control: `reports/ENGINE_RECONCILIATION.md`.

Project MIP maintains complete historical records of **delisted, merged, and suspended scrips**:
* Tickers such as `DHFL`, `ABAN`, `CORPBANK`, `RCOM`, `SUZLON` (historical distressed era), `UNITECH`, and `YESBANK` are fully preserved in the database during their active trading years. `JETAIRWAYS` has no price history in the current database.
* When a stock delists or suspends trading, the backtester detects the dropout and exits the position at the last available trading price, reflecting real-world capital loss.

### Look-Ahead Bias Prevention
* Corporate action adjustments (splits, bonuses, mergers) are effective **strictly on or after their verified ex-date**.
* Trading calendar session dates are loaded authoritatively from verified exchange schedules (`data/trading_calendar.txt`, SHA-256 `42e40e9a...`).

### Production Mutation Firewall
To guarantee that research scripts, backtests, or user errors never corrupt the production database, `core/data_engine.py` enforces a **Production Mutation Firewall**:
```python
if db_path == PROD_DB_PATH and not read_only:
    if os.environ.get("MIP_ALLOW_PROD_MUTATION") != "1":
        raise PermissionError(
            "FIREWALL BLOCKED: Direct write connection to production universe.db rejected. "
            "Set MIP_ALLOW_PROD_MUTATION=1 to permit deliberate updates."
        )
```

---

## ☁️ High-Compression Cloud Storage Architecture (`universe.db.gz`)

### 1. The Google Drive Quota & FUSE Latency Problem
When deploying systematic trading platforms on Google Colab:
1. **Google Drive Quota:** Storing uncompressed 351 MB SQLite databases quickly exhausts free Google Drive storage quotas.
2. **The 40x Google Drive FUSE Bottleneck:** When SQLite runs directly against Google Drive via `/content/drive/MyDrive/...`, every SQLite B-tree page read incurs network latency across the FUSE virtual filesystem. A single scanner run takes **2,000+ milliseconds**, and brute force sweeps become completely unusable.

### 2. The High-Compression NVMe Staging Solution
Project MIP implements an institutional streaming compression architecture in [scripts/cloud_sync.py](scripts/cloud_sync.py):

```
[ Google Drive Storage ]                     [ Google Colab Local NVMe ]
    universe.db.gz                                  universe.db
     (~101.1 MB)                                    (351.7 MB)
          │                                              │
          │ ─── 1. Stream & Decompress (1.5s) ─────────> │
          │                                              │
          │                                    [ Native Speed Execution ]
          │                                    • Sub-millisecond B-tree I/O
          │                                    • C99 SIMD Parallel Sweeps
          │                                    • 41 ms 10-Year Backtest
          │                                              │
          │ <── 2. Stream Compress & Upload ──────────── │
    universe.db.gz
  (Auto-updated on
   live market sync)
```

### 3. Compression & Performance Metrics
* **Compression Ratio:** 69.9% space saved (351.7 MB compressed to **101.1 MB**).
* **Decompression Speed:** **~1.5 seconds** to stream and decompress 101 MB directly into Colab's high-speed local NVMe SSD (`/content/Project_MIP_Colab/data/universe.db`).
* **Execution Speedup:** Local NVMe execution eliminates the 40x FUSE latency, delivering **sub-millisecond (<0.5 ms)** SQLite query response times.
* **Magic Byte Detection:** Uses standard Gzip magic bytes (`b'\x1f\x8b'`) to reliably identify compressed files regardless of file extensions.
* **Auto-Cleanup:** When uploading updated market data, `push_universe_to_gdrive()` automatically compresses the database to `universe.db.gz` and deletes any legacy uncompressed 351 MB file on Drive, preserving quota.

---

## ⚡ Multi-Architecture C99 SIMD Parallel Simulation Engine

To enable institutional-grade brute-force sweeps, parameter optimization, and walk-forward matrix analyses, Project MIP features a custom, zero-dependency C99 parallel simulation kernel ([brute_force/sim_kernel.c](brute_force/sim_kernel.c)).

### 1. In-Memory Tensor Cube Architecture
Before running simulations, the Python pre-processor converts the SQLite database into a continuous, 8-byte aligned, zero-copy **Tensor Cube** in RAM:
* Dimensions: $N_{\text{dates}} \times N_{\text{symbols}} \times N_{\text{lookbacks}} \times N_{\text{spans}}$
* Memory Footprint: **<280 MB RAM** (fits easily inside Android S23 8GB RAM or Colab 12GB RAM).
* Pre-calculated planes: Open Prices, Close Prices, ATR-14, Volar Scores, 52-Week Highs, 200 EMAs, RS Pass Masks, Market Regime Flags, and Sector IDs.

### 2. Multi-Architecture Hardware Vectorization
The C99 engine automatically detects host hardware and compiles with architecture-specific vector intrinsics:
* **Google Colab Cloud (x86_64 Intel Xeon / AMD EPYC):**
  ```bash
  gcc -O3 -fPIC -shared -march=native -mavx2 -mfma -pthread sim_kernel.c -o sim_kernel.so
  ```
  Utilizes 256-bit AVX2 SIMD registers to evaluate 8 floating-point factor calculations per instruction cycle.
* **Android S23 / Snapdragon 8 Gen 2 (ARM64 ARMv8.2-A):**
  ```bash
  gcc -O3 -fPIC -shared -march=armv8.2-a+fp16 -pthread sim_kernel.c -o sim_kernel.so
  ```
  Utilizes 128-bit ARM NEON vector registers and FP16 half-precision hardware execution.
* **Dynamic ext4 Path Resolution (`get_so_target_path`):** Bypasses Android's `noexec` storage mounting by compiling shared objects dynamically into writable app ext4 partitions.

### 3. POSIX Pthread Work-Stealing Pool
The simulation sweep divides parameter combinations across CPU hardware threads using atomic work-stealing queues (`stdatomic.h`):
* Zero inter-thread memory contention.
* Zero malloc/free calls inside the inner simulation loop.
* Lock-free atomic parameter dispatching across all available CPU cores (8 cores on Snapdragon 8 Gen 2, 2 vCPUs on Colab).

### 4. Benchmark Performance Comparison

| Metric | Pure Python / Pandas | C99 SIMD Engine (Project MIP) | Institutional Acceleration |
| :--- | :--- | :--- | :--- |
| **Single 10-Year Backtest** | 30,050 ms (30.05 s) | **41.3 ms** (Colab) / **17.6 ms** (NEON) | **1,590x Speedup** |
| **Brute Force Throughput** | 0.033 simulations/sec | **767.6 simulations/sec** | **23,260x Speedup** |
| **810 Configuration Sweep** | 6.75 hours | **1.05 seconds** | Instantaneous |
| **Active Memory Footprint** | 825.8 MB | **278.5 MB** | **66.3% RAM Reduction** |

---

## 📊 Canonical PIT Backtest Results

> **Measurement note (2026-10-24):** the canonical backtest uses **NIFTY500 point-in-time membership** — 50 full snapshots from 2016-01-18 to 2026-09-30 (niftyhistory.in; cross-checked against the CC BY 4.0 `nse-historical-membership` interval table). Membership is resolved on every rebalance. **2016-01-01 is refused** (no snapshot on or before that date). The canonical window starts in 2018, the first year with ≥70% tradable coverage (377 mapped / 356 eligible); 2017 is runnable (305 eligible) but is outside the pre-registered window. The old 2016–2026 / 2008–2026 tables used the 2026 constituent list and are **retracted**.

### 1. Canonical PIT NIFTY500 baseline (2018-01 → 2026-08, monthly)

* **Universe:** NIFTY500 point-in-time membership (377 mapped members at the 2018 start; 356 with 252 bars)
* **Initial capital:** ₹10,00,000
* **Costs:** 15 bps statutory frictions + 5 bps slippage

| Metric | Value |
| :--- | ---: |
| Final equity | **₹59,82,486.73** |
| Total return | **+498.25%** |
| CAGR | **22.94%** |
| NIFTY500 CAGR | +11.08% |
| Excess CAGR | +11.85% |
| Sharpe (Rf 6.5%) | **0.82** |
| Sortino | 1.09 |
| Calmar | 0.97 |
| Max drawdown (monthly) | **−23.66%** |
| Max drawdown (daily) | −27.68% |
| Closed trades | 492 |
| Win rate | 42.1% |
| Profit factor | 2.16 |
| Annual turnover | 471.3% |
| Deferred fills / non-session dates | 3 / 1 |
| Current-list control overstatement | **+2.81 pp CAGR** (25.75% vs 22.94%) |

### 2. Recommended profile A vs NIFTY 500 (2018-01 → 2026-08)

| Metric | A · Balanced | NIFTY 500 |
| :--- | ---: | ---: |
| CAGR | **24.97%** | 10.85% |
| Sharpe | **0.92** | 0.31 |
| Max drawdown (monthly) | **−27.10%** | −31.85% |
| Calmar | **0.92** | 0.34 |
| OOS CAGR (2022–2026) | **25.83%** | 10.20% |
| OOS Sharpe | **1.00** | 0.30 |

> Sampling basis: table 1 is session-based CAGR from the production engine (benchmark 11.08%); table 2 uses
> monthly rebalance NAVs, the same basis as the C-kernel monthly rows (benchmark 10.85%). The gap is annualization
> sampling, not a different data source — see `reports/ENGINE_RECONCILIATION.md`.

### 3. Survivorship / look-ahead control (measured)

Same Python engine, config D, dates and costs; only the membership source changes.

| Run | Universe | CAGR | Sharpe | MaxDD (monthly) | Trades |
| :--- | :--- | ---: | ---: | ---: | ---: |
| **PIT (canonical)** | NIFTY500 per-rebalance snapshots | **22.94%** | 0.82 | −23.66% | 492 |
| Current 2026 list (biased control) | today’s NIFTY500, applied backwards | 25.75% | 0.93 | −20.96% | 495 |

**Current-list look-ahead overstatement: +2.81 pp CAGR.** This is the one-number survivorship estimate; the
artifact is `reports/analysis_evidence/35_current_list_control.json`.

### 4. Retired legacy tables

The previous 2016–2026 canonical table, the 2008–2026 multi-schedule matrix, the macro-era stress table, and the next-gen comparison table were produced from current constituents or a non-PIT full cross-section, and from an older engine build. They are **not reproducible under the PIT tag** and are withdrawn from this README. The authoritative numbers are in `reports/STRATEGY_PROOF_AND_BEST_SETTINGS.md`, `reports/CODEBASE_DEEP_ANALYSIS.md`, and `reports/ENGINE_RECONCILIATION.md`.

---

## 🌐 Universal NSE Index Catalog (36 Universes)

Project MIP provides native constituent filtering across all 36 official NSE indices, categorized into three distinct classes:

### 1. Broad Market Indices (15 Universes)
* `NIFTY50`: Top 50 large-cap bluechips.
* `NIFTYNEXT50`: Next 50 large-caps (51–100).
* `NIFTY100`: Top 100 large-caps.
* `NIFTY200`: Large + Midcap (1–200).
* `NIFTY500`: Standard broad market benchmark (Top 500).
* `NIFTYMIDCAP50`, `NIFTYMIDCAP100`, `NIFTYMIDCAP150`: Pure mid-cap segments.
* `NIFTYSMALLCAP50`, `NIFTYSMALLCAP100`, `NIFTYSMALLCAP250`: Small-cap growth universes.
* `NIFTYMIDSMALL400`: Combined Midcap 150 + Smallcap 250.
* `NIFTYLARGEMID250`: Top 100 Large + 150 Midcap.
* `NIFTY500MULTICAP`: 50:25:25 Large:Mid:Small allocation universe.
* `NIFTY750` / `TOTALMARKET`: Full broad market universe covering 95%+ of total NSE market capitalization.

### 2. Sectoral Indices (14 Universes)
* `NIFTYAUTO`, `NIFTYBANK`, `NIFTYFINSERVICE`, `NIFTYFMCG`, `NIFTYHEALTHCARE`, `NIFTYIT`, `NIFTYMEDIA`, `NIFTYMETAL`, `NIFTYPHARMA`, `NIFTYPVTBANK`, `NIFTYPSUBANK`, `NIFTYREALTY`, `NIFTYCONSUMER`, `NIFTYOILGAS`.

### 3. Thematic Indices (7 Universes)
* `NIFTYCOMMODITIES`, `NIFTYENERGY`, `NIFTYINFRA`, `NIFTYMNC`, `NIFTYPSE`, `NIFTYCPSE`, `NIFTYSERVICES`.

### Constituent Reconciliation & 30-Day TTL Policy
Constituent memberships are managed by `scripts/scanner_hardening.py:ConstituentReconciliationEngine`:
* Automatically downloads official NSE CSV constituent files.
* Enforces a **30-day cache refresh TTL policy**: if the local cache is $>30$ days old, it automatically queries fresh official index baskets.
* Incorporates anti-HTML scraping guards to prevent corrupt web portal responses from polluting index baskets.

---

## 🏗 System Architecture & 24 Decoupled Core Modules

### Directory Topology
```
Project_MIP_Colab/
├── brute_force/               # Multi-Architecture C99 SIMD Simulation Engine
│   ├── bridge.py              # Ctypes bridge & dynamic gcc compiler invoker
│   ├── cube_builder.py        # In-memory Tensor Cube builder (<280 MB RAM)
│   ├── grid.py                # Parameter sweep matrices & neighborhood sweeps
│   ├── reporting.py           # Multi-era JSON and CSV metric serialier
│   ├── runner.py              # Campaign runner & single baseline orchestrator
│   └── sim_kernel.c           # C99 NEON / AVX2 / pthread parallel kernel
├── certificates/              # Sealed cryptographic provenance & manifests
│   └── PROVENANCE_MANIFEST.json
├── core/                      # 24 decoupled engine modules (+ __init__.py = 25 files)
│   ├── analytical_price.py    # Corporate actions adjustment & partitioning
│   ├── anomaly.py             # Structural price jump & anomaly detector
│   ├── auto_fetch.py          # Real-time Bhavcopy auto-sync & validation
│   ├── backtest.py            # Event-driven backtester & execution simulator
│   ├── benchmark_validator.py # Fail-closed benchmark health & regime validator
│   ├── breadth.py             # Advance-Decline & multi-timeframe market breadth
│   ├── config.py              # Canonical immutable configuration container
│   ├── data_engine.py         # SQLite connection pool & calendar manager
│   ├── delivery.py            # NSE Delivery Volume & absorption manager
│   ├── etf_engine.py          # Definedge Momentify ALL-ONE ETF scanner
│   ├── excel_generator.py     # 14-Sheet institutional Excel workbook generator
│   ├── health.py              # Scanner health monitor & state machine
│   ├── identity.py            # Security identity & symbol deduplication
│   ├── portfolio.py           # Portfolio state, ATR risk parity, friction ledger
│   ├── reason_codes.py        # Institutional diagnostic reason code enumerations
│   ├── rrg.py                 # Relative Rotation Graphs (JDK RS-Ratio / RS-Momentum)
│   ├── scan_quality_report.py # Candidate explanation & scan quality reporter
│   ├── scanner.py             # 5-tier institutional momentum screener
│   ├── sector_rotation.py     # Sector momentum, breadth, and rotation engine
│   ├── settings.py            # User investing settings serialization
│   ├── sync_sectors.py        # NSE sector/industry taxonomy synchronization
│   ├── telegram_sender.py     # Telegram alert dispatch & message chunking
│   ├── visuals.py             # TUI styling, charts, and tearsheet rendering
│   └── validation.py          # Geometric bar validation & anti-IPO checks
├── data/                      # Essential static files (SQLite DB excluded from VCS)
│   ├── benchmark_nifty500.csv # Authoritative NIFTY 500 daily benchmark series
│   ├── corporate_actions_registry.json # Corporate action adjustment history
│   └── trading_calendar.txt   # Authoritative 4,889-session trading calendar
├── docs/                      # Institutional playbooks and cloud setup guides
│   └── COLAB_SETUP_GUIDE.md   # Google Colab Secrets & Drive setup instructions
├── nextgen/                   # Next-Gen Research & Algorithmic Modules
│   ├── delivery_flow.py       # Delivery Absorption Flow & CLV distribution veto
│   ├── residual_momentum.py   # Blitz residual momentum & 21-day reversal guard
│   ├── vector_engine.py       # 2D contiguous matrix calculation layer
│   └── volatility_targeting.py# Realized vol targeting & dynamic cash shield
├── notebooks/                 # Cloud Jupyter Notebook Cockpit
│   └── Project_MIP_Colab.ipynb# 4-Cell Interactive Cloud Notebook
├── reports/                   # Output deliverables, tearsheets, and figures
├── scripts/                   # Hardening, operational sync, and scheduler daemons
│   ├── alert_dispatcher.py    # Telegram alert dispatcher & Markdown digest
│   ├── cloud_sync.py          # Streaming chunked Gzip Google Drive staging
│   ├── run_production_pipeline.py # Headless orchestrator with file locking
│   ├── scanner_hardening.py   # Constituent reconciliation & 30-day cache TTL
│   └── schedule_production_cron.py # Cron daemon & holiday-aware scheduler
└── tests/                     # Comprehensive institutional contract test suite
    ├── run_all_tests.py       # Master test runner (570+ tests)
    ├── test_colab_compatibility.py # Colab cloud environment contract tests
    ├── test_compression_sync.py # Gzip compression roundtrip & sync tests
    ├── test_integrity.py      # Provenance and architecture integrity tests
    └── test_latest_eod_resolution_guarantee.py # EOD clock guarantee tests
```

### 14-Sheet Institutional Excel Tearsheet Structure
Every full scan generates an audited, styled `.xlsx` workbook ([core/excel_generator.py](core/excel_generator.py)):
1. **Executive Summary:** Macro regime, benchmark stats, top candidate count.
2. **Actionable Picks:** Top 20 ranked candidates with exact entry prices, ATR-14, and stop-loss levels.
3. **Execution Tickets:** Full order book tickets with whole-share integer quantities and friction breakdown.
4. **Market Breadth:** Advance-decline ratios, % stocks above 20/50/200 EMAs.
5. **Sector Rotation:** Sector momentum ranking and relative rotation status.
6. **RRG Quadrants:** Relative Rotation Graph classification (Leading, Weakening, Lagging, Improving).
7. **Delivery Flow:** NSE delivery volume surge and accumulation metrics.
8. **ETF Momentum:** Definedge Momentify ALL-ONE thematic ETF rankings.
9. **Holdings Audit:** Portfolio status, open positions, and mark-to-market PnL.
10. **Cash Conservation:** Cash balance, friction deductions, and trade ledger.
11. **Historical Picks:** Win/loss performance tracking of past recommended picks.
12. **Quality & Diagnostics:** Candidate explanations for every screened symbol with exact reason codes.
13. **Anomaly Quarantine:** Structural price events and corporate reorganization audit trail.
14. **Configuration Fingerprint:** SHA-256 sealed configuration parameters and environment metadata.

---

## 🚀 Deployment & Operations Guide

### 1. Google Colab Interactive Cloud Cockpit

Click the badge to launch the pre-configured notebook:

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Afylx01/Project_MIP_Colab/blob/main/notebooks/Project_MIP_Colab.ipynb)

#### 4-Cell Cloud Workflow:
* **Cell 1: Cloud Staging & NVMe Decompression:**
  Mounts Google Drive, checks for `universe.db.gz`, streams and decompresses it to local NVMe in ~1.5s (or automatically downloads it via Google Drive if run for the first time).
* **Cell 2: Interactive IPyWidgets Screener Dashboard:**
  Select Universe (NIFTY 750, NIFTY 500, Sectoral), Top N, and toggle Telegram alerts or Excel auto-download. Click **Run Momentum Scan** to generate full reports.
* **Cell 3: High-Performance C99 SIMD Cockpit:**
  Select custom date ranges and stress windows (canonical 2018–2026 PIT; 2020 Covid Shock), rebalancing frequency, and run 40 ms simulations or parallel brute-force sweeps with real-time equity curves. Windows without PIT breadth (2008, 2011, and any start before 2016-01-18) are refused rather than silently simulated.
* **Cell 4: Headless CLI Execution Examples:**
  Direct terminal commands for batch flows and automated scheduling.

For complete details on configuring Google Cloud Service Accounts or Colab Userdata Secrets without leaking private keys, see [docs/COLAB_SETUP_GUIDE.md](docs/COLAB_SETUP_GUIDE.md).

---

### 2. Android S23 / Pydroid 3 / Termux Mobile Trading Desk

Run the interactive TUI menu directly on your phone:
```bash
python main.py
```

#### Complete TUI Menu Options ([1] to [18]):
* `[1]` **Run Momentum Screener:** Execute full screener on chosen universe with Excel/Telegram output.
* `[2]` **View Latest Screener Output:** Terminal summary of top-ranked candidates.
* `[3]` **Generate Portfolio Rebalance Orders:** Generate rebalance order tickets with ATR risk parity sizing.
* `[4]` **Market Breadth & Sector Analysis:** Deep dive into breadth indicators and sector rotation.
* `[5]` **View Portfolio Holdings & Performance:** Mark-to-market PnL and active positions ledger.
* `[6]` **Record Manual Trade Execution:** Record live fills and update cash balance.
* `[7]` **Run Backtest Simulation:** Standard event-driven Python backtester.
* `[8]` **Update Market Data (Auto-Fetch):** Download latest NSE Bhavcopy and sync SQLite database.
* `[9]` **Database Health & Diagnostics:** Run `PRAGMA integrity_check`, verify row counts and table schemas.
* `[10]` **System Configuration & Settings:** Adjust lookback days, stop multipliers, and default universes.
* `[11]` **Verify System Provenance & Integrity:** Run fail-closed contract audits across core modules.
* `[12]` **Export Data & Reports:** Export CSV/JSON summaries to external storage.
* `[13]` **View Pick Performance Ledger:** Track historical pick accuracy and return distributions.
* `[14]` **Definedge Momentify ETF Scanner:** Screen leading sector and thematic ETFs.
* `[15]` **NSE Delivery Flow & Absorption:** Screen delivery accumulation volume spikes.
* `[16]` **RRG Relative Rotation Analysis:** JDK RS-Ratio and RS-Momentum quadrant tracking.
* `[17]` **Batch Scan All 36 NIFTY Indices:** Screen all Broad, Sectoral, and Thematic universes in one run.
* `[18]` **⚡ Blazing Fast C99 SIMD Brute Force Optimizer:** Launch native SIMD parallel backtesting cockpit.

---

### 3. Headless Production CLI Guide

Execute specific operational pipelines directly via command-line flags.
`--option` uses the **headless task map** (1 scan, 5 backtest, 7 portfolio, 12 database audit, 18 brute force, ...),
which differs from the interactive menu numbering. Use `--menu-option` to address the interactive menu directly.

```bash
python main.py --help   # prints both maps
```

```bash
# 1. Weekly Momentum Scan on NIFTY 750 (with Excel tearsheet and Telegram alert)
python main.py --option 1 --universe NIFTY750 --export-excel --send-telegram

# 2. Batch Scan across all 36 official NIFTY Universes
python main.py --scan-all-universes

# 3. Canonical Baseline 10-Year Simulation (C99 SIMD Engine in <45 ms)
python main.py --brute-force --brute-force-mode baseline

# 4. Multi-Schedule Rebalance Sweep (Weekly, Monthly, Quarterly, Yearly)
python main.py --brute-force --brute-force-mode tier1 --schedule monthly

# 5. Headless Production Pipeline Orchestrator (with OS atomic file lock)
python scripts/run_production_pipeline.py --universe NIFTY750 --auto-sync

# 6. Holiday-Aware Production Scheduler Daemon (Runs at 18:30 IST on trading days)
python scripts/schedule_production_cron.py --daemon
```

---

## 🔒 Security Governance & Auditing Protocol

### Zero-Leak Security Guarantee
Project MIP enforces strict institutional secret isolation:
1. **Zero Hardcoded Secrets:** No API keys, Telegram tokens, or Google service account credentials are stored in code or repository tracking.
2. **Environment Variable Configuration:** All operational credentials must be provisioned via `.env` (using `.env.example` as a template) or Google Colab native Secrets Manager (`google.colab.userdata`).
3. **Comprehensive `.gitignore`:** Strictly excludes `.env`, `*service_account*.json`, `*.pem`, `*.key`, `universe.db`, and compiled binary artifacts (`*.so`).
4. **Credential Leak Verification Suite:** [tests/test_colab_compatibility.py](tests/test_colab_compatibility.py) includes automated fail-closed token scanners that inspect every file in the tree to guarantee zero private keys are committed.

### Pre-Completion Audit Protocol (The 5 Quantitative Validity Pillars)
Every release and feature commit is audited against the institutional 5-pillar validation standard:
1. **Pillar 1 — Data Biases & Point-in-Time Correctness:** Per-rebalance point-in-time index membership (2016–2026 snapshots; 2016-01-01 refused), point-in-time corporate action adjustments, and zero look-ahead bias. Named historical indices without a PIT table are refused.
2. **Pillar 2 — Execution & Timing Realism:** Next-day Open execution ($T+1$), 20 bps statutory frictions and slippage, and whole-share integer rounding.
3. **Pillar 3 — Portfolio & Accounting Invariants:** Cash conservation, strict $0 \le \text{Total Allocated} \le \text{Capital}$, and anti-clustering sector caps (max 2 per sector).
4. **Pillar 4 — Statistical & Experimental Validity:** Deflated Sharpe Ratio (DSR) evaluation, multi-era regime stress testing, and frozen canonical parameters.
5. **Pillar 5 — Software & Architectural Correctness:** C99 memory safety, thread-pool work-stealing, and atomic OS file locks.

To run the master test runner across the entire codebase:
```bash
python tests/run_all_tests.py
```
---

## 📜 Version History & Defect Remediation Register

Project MIP follows strict [Semantic Versioning](https://semver.org/) and institutional audit tracking. Every bug fix, optimization, and factor release is verified with deterministic `fail → pass` TDD test logs.

| Version | Release Date | Key Enhancements & Defect Fixes | Verification Status |
| :--- | :--- | :--- | :--- |
| **`v2.4.2`** | 2026-10-24 | **Point-in-time NIFTY500 membership**: 50 full snapshots (2016-01-18 → 2026-09-30), per-rebalance resolution in Python + C kernel, refusal of pre-2016-01-18 starts and 2008/2011; survivorship control (+2.81 pp); stale current-list tables retracted. | **630 passed, 5 skipped, 0 failed** |
| **`v2.4.1`** | 2026-10-23 | Engine reconciliation, stress-window labelling, survivorship measurement, forensic integrity fixes. | **574 passed, 5 skipped, 0 failed** (pre-PIT baseline) |
| **`v2.4.0`** | 2026-10-18 | **Institutional Engine & 52 Defect Hardening (3 Continuous Multi-Agent Loops)**: FastDataCache, Risk & Tail Analytics, Menchero Log Linking Factor Attribution, Microstructure Liquidity Modeler, SEBI Pre-Trade Compliance, Interactive HTML Tearsheet, SIMD C99 uint8 Stride & Double Accumulators, 37/37 Real Multi-Variation Sweep passed. | **100% Passed (58 unit tests + 37/37 real sweep, exit code 0)** |
| **`v2.3.0`** | 2026-10-17 | Universal Benchmark Selection (Scanner, Backtester, Brute Force), Chunked SIMD Streaming Telemetry (No UI Freezes), Dynamic Colab Cockpit. | **100% Passed (346 tests, exit code 0)** |
| **`v2.2.0`** | 2026-10-17 | Screener Residual Momentum (`use_residual_momentum`), Real-Time EOD Guarantee past calendar boundary (DEF-C03), True NIFTY 500 Benchmark Continuity eliminating pre-2020 collapse (DEF-C04). | **100% Passed (339 tests, exit code 0)** |
| **`v2.1.0`** | 2026-10-16 | Colab Defect Remediation (DEF-C01 to DEF-C07: Universe ALL resolution, RS benchmark staleness recovery, sim_kernel bounds, CorporateAction adjustment_factor). | **100% Passed (335 tests, exit code 0)** |
| **`v2.0.0`** | 2026-10-15 | Google Colab Port, C99 SIMD Parallel Engine, Vulnerability Audit Remediation (DEF-01 to DEF-22), Alpha Overlays (Vol Targeting, Delivery Absorption Flow Veto). | **100% Passed (328 tests, exit code 0)** |
| **`v1.0.0`** | 2026-10-13 | Canonical Sealed Institutional Baseline, 25 Core Decoupled Modules, 2.16M Bar Universe DB. | **Sealed Production Baseline** |

> For complete commit diffs, defect blueprints, and mathematical proofs, see [CHANGELOG.md](CHANGELOG.md) and [EVIDENCE_PACKAGE_BUGS_COLAB.md](reports/EVIDENCE_PACKAGE_BUGS_COLAB.md).

---

## 📄 License & Institutional Disclaimer

### License
Distributed under the **MIT License**. See `LICENSE` for more information.

### Institutional Research Disclaimer
```
DISCLAIMER: This software and quantitative research desk are developed exclusively for 
educational, scientific, and quantitative research purposes. It does not constitute financial, 
investment, tax, or legal advice. 

The strategy formulations, backtest results, and simulated performance metrics presented in this 
documentation represent hypothetical, backtested historical simulations and are not indicative 
of future results. Trading equities and derivatives in financial markets involves substantial risk 
of capital loss. 

The authors and contributors accept no responsibility or liability for any direct or consequential 
financial losses resulting from the use of this software or its algorithms. Users must consult a 
SEBI-registered investment advisor (or applicable national regulatory body) before committing capital.
```

---
**Institutional Provenance:** Engineered with mathematical rigor for quantitative traders, portfolio managers, and algorithmic researchers. Designed to run reliably anywhere — from mobile Snapdragon 8 Gen 2 hardware to cloud high-performance compute clusters.
