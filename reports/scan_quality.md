# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-09_1792238219`  
**Execution Timestamp:** 2026-10-17 11:56:59  
**As-Of Market Date:** 2026-10-09  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 13.37s  

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
| **Qualified Strategy Candidates** | 3 | 6.0% |
| **Excluded / Failed Securities** | 47 | 94.0% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 27 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `BELOW_EMA200` | 18 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `PASS` | 3 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `INSUFFICIENT_HISTORY` | 1 | HISTORY | History is below mandatory 252-session minimum. |
| `NEGATIVE_MOMENTUM` | 1 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | **ADANIPORTS** | SERVICES | ₹1,761.00 | `0.39` | +26.4% | PASS | PASS | PASS |
| 2 | **TECHM** | INFORMATION TECHNOLOGY | ₹1,514.10 | `0.32` | +9.1% | PASS | PASS | PASS |
| 3 | **KOTAKBANK** | FINANCIAL SERVICES | ₹441.00 | `0.27` | +3.9% | PASS | PASS | PASS |