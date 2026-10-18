# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-16_1792364360`  
**Execution Timestamp:** 2026-10-18 22:59:20  
**As-Of Market Date:** 2026-10-16  
**Reference Benchmark:** `NIFTY500`  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 70.88s  

---

## 1. Scanner Health State: **DEGRADED**

- **Allow Actionable Buys:** `True`
- **Universe Coverage:** 89.69% (670 / 747 symbols)
- **Benchmark Status:** `BULL` (Regime: `NORMAL`)
- **Benchmark Level vs 20 EMA:** ₹22,270.05 vs 20 EMA ₹22,256.81

### Next-Gen Alpha Overlays & Risk Controls:

| Overlay Dimension | Status | Formulation / Reference |
|---|---|---|
| **Residual Momentum** | `BYPASS` | Blitz et al. (2011) 40% Volar / 60% Idiosyncratic Alpha |
| **Dynamic Volatility Cash Shield** | `BYPASS` | Harvey et al. (2018) 12% Realized Target Volatility |
| **Delivery Flow Absorption Veto** | `BYPASS` | Microstructure Distribution Spikes Veto |

### Non-Critical Health Warnings:
- ℹ️ Degraded universe coverage: 89.7% is below standard 90% threshold
- ℹ️ 3 unverified market data anomalies flagged during scan

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 747 | 100.0% |
| **Data-Valid Securities** | 670 | 89.69% |
| **Qualified Strategy Candidates** | 206 | 27.6% |
| **Excluded / Failed Securities** | 541 | 72.4% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 368 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 206 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `INSUFFICIENT_HISTORY` | 74 | HISTORY | History is below mandatory 252-session minimum. |
| `BELOW_EMA200` | 67 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `NEGATIVE_MOMENTUM` | 29 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |
| `UNRESOLVED_STRUCTURAL_PRICE_EVENT` | 2 | DATA_INTEGRITY | Unresolved structural price discontinuity (drop >= 40% or jump >= 60%) in lookback window. |
| `CORPORATE_ACTION_REVIEW_REQUIRED` | 1 | DATA_INTEGRITY | Material corporate reorganization requires review; unadjusted or unverified factor. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar | Res Alpha | 1Y Return | Delivery Action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **STLTECH** | TELECOMMUNICATION | ₹865.90 | `10.81` | `N/A` | +668.8% | APPROVED | PASS |
| 2 | **CUPID** | FAST MOVING CONSUMER GOODS | ₹353.70 | `10.48` | `N/A` | +608.9% | APPROVED | PASS |
| 3 | **WELCORP** | CAPITAL GOODS | ₹2,571.50 | `4.74` | `N/A` | +212.7% | APPROVED | PASS |
| 4 | **SKYGOLD** | CONSUMER DURABLES | ₹1,060.60 | `4.72` | `N/A` | +226.8% | APPROVED | PASS |
| 5 | **LAURUSLABS** | HEALTHCARE | ₹2,060.10 | `4.70` | `N/A` | +135.1% | APPROVED | PASS |
| 6 | **HFCL** | TELECOMMUNICATION | ₹256.01 | `4.67` | `N/A` | +241.6% | APPROVED | PASS |
| 7 | **SANSERA** | AUTOMOBILE AND AUTO COMPONENTS | ₹4,120.70 | `4.63` | `N/A` | +194.6% | APPROVED | PASS |
| 8 | **CPPLUS** | CAPITAL GOODS | ₹4,063.60 | `4.46` | `N/A` | +199.9% | APPROVED | PASS |
| 9 | **SHILPAMED** | HEALTHCARE | ₹937.60 | `3.96` | `N/A` | +165.6% | APPROVED | PASS |
| 10 | **ATHERENERG** | AUTOMOBILE AND AUTO COMPONENTS | ₹1,470.00 | `2.91` | `N/A` | +139.0% | APPROVED | PASS |
| 11 | **KTKBANK** | FINANCIAL SERVICES | ₹329.85 | `2.63` | `N/A` | +92.8% | APPROVED | PASS |
| 12 | **TMB** | FINANCIAL SERVICES | ₹857.30 | `2.60` | `N/A` | +100.5% | APPROVED | PASS |
| 13 | **AETHER** | CHEMICALS | ₹1,538.60 | `2.55` | `N/A` | +106.5% | APPROVED | PASS |
| 14 | **ARVIND** | TEXTILES | ₹525.70 | `2.14` | `N/A` | +83.7% | APPROVED | PASS |
| 15 | **PGIL** | TEXTILES | ₹1,289.20 | `1.96` | `N/A` | +97.4% | APPROVED | PASS |
| 16 | **GAEL** | FAST MOVING CONSUMER GOODS | ₹174.14 | `1.94` | `N/A` | +71.5% | APPROVED | PASS |
| 17 | **NAVINFLUOR** | CHEMICALS | ₹8,167.00 | `1.92` | `N/A` | +70.2% | APPROVED | PASS |
| 18 | **CHENNPETRO** | OIL GAS & CONSUMABLE FUELS | ₹1,406.60 | `1.68` | `N/A` | +92.5% | APPROVED | PASS |
| 19 | **NAZARA** | MEDIA ENTERTAINMENT & PUBLICATION | ₹418.15 | `1.55` | `N/A` | +59.4% | APPROVED | PASS |
| 20 | **GESHIP** | SERVICES | ₹1,507.40 | `1.48` | `N/A` | +51.1% | APPROVED | PASS |