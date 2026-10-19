# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-16_1792388977`  
**Execution Timestamp:** 2026-10-19 05:49:37  
**As-Of Market Date:** 2026-10-16  
**Reference Benchmark:** `NIFTY500`  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 10.5s  

---

## 1. Scanner Health State: **HEALTHY**

- **Allow Actionable Buys:** `True`
- **Universe Coverage:** 93.33% (28 / 30 symbols)
- **Benchmark Status:** `BULL` (Regime: `NORMAL`)
- **Benchmark Level vs 20 EMA:** ₹22,270.05 vs 20 EMA ₹22,256.81

### Next-Gen Alpha Overlays & Risk Controls:

| Overlay Dimension | Status | Formulation / Reference |
|---|---|---|
| **Residual Momentum** | `BYPASS` | Blitz et al. (2011) 40% Volar / 60% Idiosyncratic Alpha |
| **Dynamic Volatility Cash Shield** | `BYPASS` | Harvey et al. (2018) 12% Realized Target Volatility |
| **Delivery Flow Absorption Veto** | `BYPASS` | Microstructure Distribution Spikes Veto |

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 30 | 100.0% |
| **Data-Valid Securities** | 28 | 93.33% |
| **Qualified Strategy Candidates** | 9 | 30.0% |
| **Excluded / Failed Securities** | 21 | 70.0% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 14 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 9 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `BELOW_EMA200` | 5 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `INSUFFICIENT_HISTORY` | 2 | HISTORY | History is below mandatory 252-session minimum. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar | Res Alpha | 1Y Return | Delivery Action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **GLAND** | HEALTHCARE | ₹3,043.40 | `1.74` | `N/A` | +59.0% | APPROVED | PASS |
| 2 | **ABB** | CAPITAL GOODS | ₹6,801.00 | `1.14` | `N/A` | +35.0% | APPROVED | PASS |
| 3 | **OFSS** | INFORMATION TECHNOLOGY | ₹10,386.00 | `0.66` | `N/A` | +21.2% | APPROVED | PASS |
| 4 | **BOSCHLTD** | AUTOMOBILE AND AUTO COMPONENTS | ₹45,560.00 | `0.65` | `N/A` | +19.0% | APPROVED | PASS |
| 5 | **NAM-INDIA** | FINANCIAL SERVICES | ₹1,065.30 | `0.60` | `N/A` | +23.7% | APPROVED | PASS |