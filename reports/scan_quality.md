# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-19_1792587091`  
**Execution Timestamp:** 2026-10-21 12:51:31  
**As-Of Market Date:** 2026-10-19  
**Reference Benchmark:** `NIFTY500`  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 48.21s  

---

## 1. Scanner Health State: **DEGRADED**

- **Allow Actionable Buys:** `False`
- **Universe Coverage:** 95.17% (473 / 497 symbols)
- **Benchmark Status:** `DEFENSIVE` (Regime: `DEFENSIVE`)
- **Benchmark Level vs 20 EMA:** ₹22,041.60 vs 20 EMA ₹22,236.31

### Next-Gen Alpha Overlays & Risk Controls:

| Overlay Dimension | Status | Formulation / Reference |
|---|---|---|
| **Residual Momentum** | `BYPASS` | Blitz et al. (2011) 40% Volar / 60% Idiosyncratic Alpha |
| **Dynamic Volatility Cash Shield** | `BYPASS` | Harvey et al. (2018) 12% Realized Target Volatility |
| **Delivery Flow Absorption Veto** | `BYPASS` | Microstructure Distribution Spikes Veto |

### Non-Critical Health Warnings:
- ℹ️ 1 unverified market data anomalies flagged during scan

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 497 | 100.0% |
| **Data-Valid Securities** | 473 | 95.17% |
| **Qualified Strategy Candidates** | 120 | 24.1% |
| **Excluded / Failed Securities** | 377 | 75.9% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 274 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 120 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `BELOW_EMA200` | 63 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `INSUFFICIENT_HISTORY` | 23 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 16 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |
| `CORPORATE_ACTION_REVIEW_REQUIRED` | 1 | DATA_INTEGRITY | Material corporate reorganization requires review; unadjusted or unverified factor. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar | Res Alpha | 1Y Return | Delivery Action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **STLTECH** | TELECOMMUNICATION | ₹887.25 | `10.51` | `N/A` | +648.7% | APPROVED | PASS |
| 2 | **CUPID** | FAST MOVING CONSUMER GOODS | ₹336.30 | `9.80` | `N/A` | +572.0% | APPROVED | PASS |
| 3 | **WELCORP** | CAPITAL GOODS | ₹2,592.90 | `4.80` | `N/A` | +215.3% | APPROVED | PASS |
| 4 | **HFCL** | TELECOMMUNICATION | ₹268.81 | `4.79` | `N/A` | +248.1% | APPROVED | PASS |
| 5 | **LAURUSLABS** | HEALTHCARE | ₹2,069.00 | `4.76` | `N/A` | +136.8% | APPROVED | PASS |
| 6 | **SANSERA** | AUTOMOBILE AND AUTO COMPONENTS | ₹4,150.30 | `4.56` | `N/A` | +191.3% | APPROVED | PASS |
| 7 | **CPPLUS** | CAPITAL GOODS | ₹4,010.00 | `4.07` | `N/A` | +181.9% | APPROVED | PASS |
| 8 | **ATHERENERG** | AUTOMOBILE AND AUTO COMPONENTS | ₹1,459.00 | `2.72` | `N/A` | +129.6% | APPROVED | PASS |
| 9 | **AETHER** | CHEMICALS | ₹1,521.40 | `2.47` | `N/A` | +103.6% | APPROVED | PASS |
| 10 | **ACUTAAS** | HEALTHCARE | ₹3,253.40 | `2.46` | `N/A` | +110.1% | APPROVED | PASS |