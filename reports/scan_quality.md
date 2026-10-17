# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-09_1792236119`  
**Execution Timestamp:** 2026-10-17 11:21:59  
**As-Of Market Date:** 2026-10-09  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 9.74s  

---

## 1. Scanner Health State: **HEALTHY**

- **Allow Actionable Buys:** `False`
- **Universe Coverage:** 94.77% (471 / 497 symbols)
- **Benchmark Status:** `DEFENSIVE` (Regime: `DEFENSIVE`)

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 497 | 100.0% |
| **Data-Valid Securities** | 471 | 94.77% |
| **Qualified Strategy Candidates** | 126 | 25.4% |
| **Excluded / Failed Securities** | 371 | 74.6% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 266 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `PASS` | 126 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `BELOW_EMA200` | 64 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `INSUFFICIENT_HISTORY` | 26 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 15 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | **CUPID** | FAST MOVING CONSUMER GOODS | ₹366.10 | `12.74` | +751.5% | PASS | PASS | PASS |
| 2 | **STLTECH** | TELECOMMUNICATION | ₹1,015.20 | `12.22` | +749.9% | PASS | PASS | PASS |
| 3 | **HFCL** | TELECOMMUNICATION | ₹260.40 | `4.87` | +249.7% | PASS | PASS | PASS |
| 4 | **MTARTECH** | CAPITAL GOODS | ₹7,781.50 | `4.84` | +295.8% | PASS | PASS | PASS |
| 5 | **LAURUSLABS** | HEALTHCARE | ₹2,036.60 | `4.75` | +136.3% | PASS | PASS | PASS |
| 6 | **WELCORP** | CAPITAL GOODS | ₹2,640.40 | `4.64` | +203.9% | PASS | PASS | PASS |
| 7 | **SANSERA** | AUTOMOBILE AND AUTO COMPONENTS | ₹4,124.70 | `4.39` | +183.8% | PASS | PASS | PASS |
| 8 | **AETHER** | CHEMICALS | ₹1,748.10 | `3.24` | +133.1% | PASS | PASS | PASS |
| 9 | **SONACOMS** | AUTOMOBILE AND AUTO COMPONENTS | ₹783.30 | `2.87` | +90.3% | PASS | PASS | PASS |
| 10 | **ACUTAAS** | HEALTHCARE | ₹3,160.60 | `2.79` | +125.5% | PASS | PASS | PASS |
| 11 | **MCX** | FINANCIAL SERVICES | ₹3,318.20 | `2.67` | +102.6% | PASS | PASS | PASS |
| 12 | **FEDERALBNK** | FINANCIAL SERVICES | ₹330.00 | `2.54` | +66.2% | PASS | PASS | PASS |
| 13 | **NAVINFLUOR** | CHEMICALS | ₹8,352.50 | `2.27` | +83.0% | PASS | PASS | PASS |
| 14 | **WELSPUNLIV** | TEXTILES | ₹223.75 | `2.04` | +93.7% | PASS | PASS | PASS |
| 15 | **HONASA** | FAST MOVING CONSUMER GOODS | ₹468.70 | `1.81` | +59.4% | PASS | PASS | PASS |
| 16 | **CHENNPETRO** | OIL GAS & CONSUMABLE FUELS | ₹1,487.70 | `1.73` | +94.3% | PASS | PASS | PASS |
| 17 | **GESHIP** | SERVICES | ₹1,533.70 | `1.49` | +50.9% | PASS | PASS | PASS |
| 18 | **AEGISLOG** | OIL GAS & CONSUMABLE FUELS | ₹1,388.90 | `1.48` | +68.0% | PASS | PASS | PASS |
| 19 | **ACMESOLAR** | POWER | ₹418.10 | `1.16` | +44.2% | PASS | PASS | PASS |
| 20 | **NYKAA** | CONSUMER SERVICES | ₹343.00 | `1.13` | +30.7% | PASS | PASS | PASS |