# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-14_1792258257`  
**Execution Timestamp:** 2026-10-17 17:30:57  
**As-Of Market Date:** 2026-10-14  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 15.23s  

---

## 1. Scanner Health State: **HEALTHY**

- **Allow Actionable Buys:** `False`
- **Universe Coverage:** 98.0% (49 / 50 symbols)
- **Benchmark Status:** `DEFENSIVE` (Regime: `DEFENSIVE`)

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 50 | 100.0% |
| **Data-Valid Securities** | 49 | 98.0% |
| **Qualified Strategy Candidates** | 5 | 10.0% |
| **Excluded / Failed Securities** | 45 | 90.0% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 26 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `BELOW_EMA200` | 17 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `PASS` | 5 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `INSUFFICIENT_HISTORY` | 1 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 1 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | **ADANIPORTS** | SERVICES | ₹1,748.70 | `0.86` | +24.6% | PASS | PASS | PASS |
| 2 | **NESTLEIND** | FAST MOVING CONSUMER GOODS | ₹1,383.20 | `0.80` | +16.5% | PASS | PASS | PASS |
| 3 | **TECHM** | INFORMATION TECHNOLOGY | ₹1,575.20 | `0.43` | +12.1% | PASS | PASS | PASS |
| 4 | **AXISBANK** | FINANCIAL SERVICES | ₹1,264.60 | `0.30` | +7.2% | PASS | PASS | PASS |
| 5 | **KOTAKBANK** | FINANCIAL SERVICES | ₹438.05 | `0.10` | +2.0% | PASS | PASS | PASS |