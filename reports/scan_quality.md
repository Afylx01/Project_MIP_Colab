# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-16_1792242618`  
**Execution Timestamp:** 2026-10-17 13:10:18  
**As-Of Market Date:** 2026-10-16  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 2.66s  

---

## 1. Scanner Health State: **DEGRADED**

- **Allow Actionable Buys:** `True`
- **Universe Coverage:** 98.0% (49 / 50 symbols)
- **Benchmark Status:** `BULL` (Regime: `NORMAL`)

### Non-Critical Health Warnings:
- ℹ️ 1 unverified market data anomalies flagged during scan

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 50 | 100.0% |
| **Data-Valid Securities** | 49 | 98.0% |
| **Qualified Strategy Candidates** | 6 | 12.0% |
| **Excluded / Failed Securities** | 44 | 88.0% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 27 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `BELOW_EMA200` | 13 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `PASS` | 6 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `NEGATIVE_MOMENTUM` | 3 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |
| `CORPORATE_ACTION_REVIEW_REQUIRED` | 1 | DATA_INTEGRITY | Material corporate reorganization requires review; unadjusted or unverified factor. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar Score | 1Y Return | Filter 1 | Filter 2 | Filter 3 |
|---|---|---|---|---|---|---|---|---|
| 1 | **BAJAJ-AUTO** | AUTOMOBILE AND AUTO COMPONENTS | ₹10,405.00 | `0.69` | +15.9% | PASS | PASS | PASS |
| 2 | **ADANIPORTS** | SERVICES | ₹1,750.80 | `0.60` | +23.0% | PASS | PASS | PASS |
| 3 | **TECHM** | INFORMATION TECHNOLOGY | ₹1,790.00 | `0.54` | +26.4% | PASS | PASS | PASS |