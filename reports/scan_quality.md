# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-16_1792486612`  
**Execution Timestamp:** 2026-10-20 08:56:52  
**As-Of Market Date:** 2026-10-16  
**Reference Benchmark:** `NIFTY500`  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 51.27s  

---

## 1. Scanner Health State: **DEGRADED**

- **Allow Actionable Buys:** `True`
- **Universe Coverage:** 95.17% (473 / 497 symbols)
- **Benchmark Status:** `BULL` (Regime: `NORMAL`)
- **Benchmark Level vs 20 EMA:** ₹22,270.05 vs 20 EMA ₹22,256.81

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
| **Qualified Strategy Candidates** | 136 | 27.4% |
| **Excluded / Failed Securities** | 361 | 72.6% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 254 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 136 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `BELOW_EMA200` | 64 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `INSUFFICIENT_HISTORY` | 23 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 19 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |
| `CORPORATE_ACTION_REVIEW_REQUIRED` | 1 | DATA_INTEGRITY | Material corporate reorganization requires review; unadjusted or unverified factor. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar | Res Alpha | 1Y Return | Delivery Action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **STLTECH** | TELECOMMUNICATION | ₹865.90 | `10.81` | `N/A` | +668.8% | APPROVED | PASS |
| 2 | **CUPID** | FAST MOVING CONSUMER GOODS | ₹353.70 | `10.48` | `N/A` | +608.9% | APPROVED | PASS |
| 3 | **WELCORP** | CAPITAL GOODS | ₹2,571.50 | `4.74` | `N/A` | +212.7% | APPROVED | PASS |
| 4 | **LAURUSLABS** | HEALTHCARE | ₹2,060.10 | `4.70` | `N/A` | +135.1% | APPROVED | PASS |
| 5 | **HFCL** | TELECOMMUNICATION | ₹256.01 | `4.67` | `N/A` | +241.6% | APPROVED | PASS |
| 6 | **SANSERA** | AUTOMOBILE AND AUTO COMPONENTS | ₹4,120.70 | `4.63` | `N/A` | +194.6% | APPROVED | PASS |
| 7 | **CPPLUS** | CAPITAL GOODS | ₹4,063.60 | `4.46` | `N/A` | +199.9% | APPROVED | PASS |
| 8 | **ATHERENERG** | AUTOMOBILE AND AUTO COMPONENTS | ₹1,470.00 | `2.91` | `N/A` | +139.0% | APPROVED | PASS |
| 9 | **AETHER** | CHEMICALS | ₹1,538.60 | `2.55` | `N/A` | +106.5% | APPROVED | PASS |
| 10 | **ACUTAAS** | HEALTHCARE | ₹3,206.00 | `2.55` | `N/A` | +114.2% | APPROVED | PASS |
| 11 | **FEDERALBNK** | FINANCIAL SERVICES | ₹338.00 | `2.22` | `N/A` | +57.4% | APPROVED | PASS |
| 12 | **NAVINFLUOR** | CHEMICALS | ₹8,167.00 | `1.92` | `N/A` | +70.2% | APPROVED | PASS |
| 13 | **HONASA** | FAST MOVING CONSUMER GOODS | ₹452.25 | `1.85` | `N/A` | +60.5% | APPROVED | PASS |
| 14 | **ANANDRATHI** | FINANCIAL SERVICES | ₹2,159.70 | `1.83` | `N/A` | +37.1% | APPROVED | PASS |
| 15 | **WELSPUNLIV** | TEXTILES | ₹219.30 | `1.70` | `N/A` | +78.5% | APPROVED | PASS |
| 16 | **CHENNPETRO** | OIL GAS & CONSUMABLE FUELS | ₹1,406.60 | `1.68` | `N/A` | +92.5% | APPROVED | PASS |
| 17 | **GESHIP** | SERVICES | ₹1,507.40 | `1.48` | `N/A` | +51.1% | APPROVED | PASS |
| 18 | **AEGISLOG** | OIL GAS & CONSUMABLE FUELS | ₹1,366.70 | `1.47` | `N/A` | +69.4% | APPROVED | PASS |
| 19 | **BBOX** | INFORMATION TECHNOLOGY | ₹907.25 | `1.33` | `N/A` | +60.6% | APPROVED | PASS |
| 20 | **NYKAA** | CONSUMER SERVICES | ₹345.00 | `1.30` | `N/A` | +34.9% | APPROVED | PASS |