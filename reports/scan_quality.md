# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-14_1792042590`  
**Execution Timestamp:** 2026-10-15 05:36:30  
**As-Of Market Date:** 2026-10-14  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 67.59s  

---

## 1. Scanner Health State: **HEALTHY**

- **Allow Actionable Buys:** `False`
- **Universe Coverage:** 94.97% (472 / 497 symbols)
- **Benchmark Status:** `DEFENSIVE` (Regime: `DEFENSIVE`)

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 497 | 100.0% |
| **Data-Valid Securities** | 472 | 94.97% |
| **Qualified Strategy Candidates** | 136 | 27.4% |
| **Excluded / Failed Securities** | 361 | 72.6% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 250 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 136 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `BELOW_EMA200` | 70 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `INSUFFICIENT_HISTORY` | 25 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 16 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | **STLTECH** | TELECOMMUNICATION | ₹924.65 | `11.20` | +692.2% | PASS | PASS | PASS |
| 2 | **CUPID** | FAST MOVING CONSUMER GOODS | ₹354.60 | `10.68` | +620.0% | PASS | PASS | PASS |
| 3 | **MTARTECH** | CAPITAL GOODS | ₹7,672.00 | `5.05` | +307.9% | PASS | PASS | PASS |
| 4 | **CPPLUS** | CAPITAL GOODS | ₹4,440.30 | `4.96` | +219.3% | PASS | PASS | PASS |
| 5 | **HFCL** | TELECOMMUNICATION | ₹256.65 | `4.63` | +237.5% | PASS | PASS | PASS |
| 6 | **LAURUSLABS** | HEALTHCARE | ₹2,036.90 | `4.63` | +132.8% | PASS | PASS | PASS |
| 7 | **SANSERA** | AUTOMOBILE AND AUTO COMPONENTS | ₹4,198.80 | `4.56` | +190.9% | PASS | PASS | PASS |
| 8 | **ATHERENERG** | AUTOMOBILE AND AUTO COMPONENTS | ₹1,467.00 | `3.07` | +146.6% | PASS | PASS | PASS |
| 9 | **AETHER** | CHEMICALS | ₹1,682.60 | `3.01` | +124.3% | PASS | PASS | PASS |
| 10 | **ACUTAAS** | HEALTHCARE | ₹3,160.50 | `2.57` | +115.4% | PASS | PASS | PASS |
| 11 | **NAVINFLUOR** | CHEMICALS | ₹8,457.00 | `2.32` | +84.8% | PASS | PASS | PASS |
| 12 | **MCX** | FINANCIAL SERVICES | ₹3,250.50 | `2.30` | +87.5% | PASS | PASS | PASS |
| 13 | **FEDERALBNK** | FINANCIAL SERVICES | ₹330.00 | `2.28` | +59.0% | PASS | PASS | PASS |
| 14 | **WELSPUNLIV** | TEXTILES | ₹229.58 | `1.90` | +87.1% | PASS | PASS | PASS |
| 15 | **CHENNPETRO** | OIL GAS & CONSUMABLE FUELS | ₹1,546.10 | `1.87` | +102.7% | PASS | PASS | PASS |
| 16 | **AEGISLOG** | OIL GAS & CONSUMABLE FUELS | ₹1,489.10 | `1.83` | +85.8% | PASS | PASS | PASS |
| 17 | **HONASA** | FAST MOVING CONSUMER GOODS | ₹456.55 | `1.82` | +59.5% | PASS | PASS | PASS |
| 18 | **GESHIP** | SERVICES | ₹1,543.10 | `1.51` | +51.6% | PASS | PASS | PASS |
| 19 | **BBOX** | INFORMATION TECHNOLOGY | ₹935.80 | `1.40` | +62.9% | PASS | PASS | PASS |
| 20 | **ACMESOLAR** | POWER | ₹419.75 | `1.25` | +47.4% | PASS | PASS | PASS |