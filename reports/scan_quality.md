# Quantitative Scanner Quality & Lineage Report

**Scan ID:** `SCAN_2026-10-19_1792847644`  
**Execution Timestamp:** 2026-10-24 13:14:04  
**As-Of Market Date:** 2026-10-19  
**Reference Benchmark:** `NIFTY500`  
**Strategy Version:** `MIP-Scanner-1.0`  
**Scanner Version:** `2.0.0-institutional`  
**Configuration Hash:** `6c8981f97b010ad4...`  
**Execution Runtime:** 2.5s  

---

## 1. Scanner Health State: **DEGRADED**

- **Allow Actionable Buys:** `False`
- **Universe Coverage:** 98.0% (49 / 50 symbols)
- **Benchmark Status:** `DEFENSIVE` (Regime: `DEFENSIVE`)
- **Benchmark Level vs 20 EMA:** ₹22,041.60 vs 20 EMA ₹22,236.31

### Next-Gen Alpha Overlays & Risk Controls:

| Overlay Dimension | Status | Formulation / Reference |
|---|---|---|
| **Residual Momentum** | `ACTIVE` | Blitz et al. (2011) 40% Volar / 60% Idiosyncratic Alpha |
| **Dynamic Volatility Cash Shield** | `BYPASS` | Harvey et al. (2018) 12% Realized Target Volatility |
| **Delivery Flow Absorption Veto** | `BYPASS` | Microstructure Distribution Spikes Veto |

### Non-Critical Health Warnings:
- ℹ️ 1 unverified market data anomalies flagged during scan

---

## 2. Quantitative Funnel & Reason Code Distribution

| Metric | Count | Percentage |
|---|---|---|
| **Requested Universe** | 50 | 100.0% |
| **Data-Valid Securities** | 49 | 98.0% |
| **Qualified Strategy Candidates** | 4 | 8.0% |
| **Excluded / Failed Securities** | 46 | 92.0% |

### Reason Code Histogram:

| Reason Code | Count | Category | Description |
|---|---|---|---|
| `BELOW_52W_HIGH_THRESHOLD` | 26 | STRATEGY_FILTER | Close is below 80% of 52-week rolling high. |
| `BELOW_EMA200` | 15 | STRATEGY_FILTER | Close is not strictly above the 200-day exponential moving average. |
| `PASS` | 4 | SUCCESS | Candidate fully qualified and verified across all strategy rules. |
| `NEGATIVE_MOMENTUM` | 4 | STRATEGY_FILTER | 1-year momentum return or Volar score is non-positive. |
| `CORPORATE_ACTION_REVIEW_REQUIRED` | 1 | DATA_INTEGRITY | Material corporate reorganization requires review; unadjusted or unverified factor. |

---

## 3. Top Qualified Candidates

| Rank | Symbol | Sector | Close (₹) | Volar | Res Alpha | 1Y Return | Delivery Action | Status |
|---|---|---|---|---|---|---|---|---|
| 1 | **ADANIPORTS** | SERVICES | ₹1,766.00 | `0.58` | `+0.454` | +22.2% | APPROVED | PASS |
| 2 | **TECHM** | INFORMATION TECHNOLOGY | ₹1,779.10 | `0.55` | `+0.317` | +26.4% | APPROVED | PASS |
| 3 | **KOTAKBANK** | FINANCIAL SERVICES | ₹442.30 | `0.41` | `+0.594` | +3.1% | APPROVED | PASS |