# 🏆 Top 3 Low-Drawdown Settings Combinations with Superior CAGR

**Execution Timestamp:** 2026-10-21 15:59:13 UTC  
**Universe:** NIFTY 500 (501 Liquid Equities, 1.28M Bars)  
**Validation Framework:** Train (70%, 2016–2022) vs Out-of-Sample Test (30%, 2023–2026) Walk-Forward  
**Primary Objective:** Maximize Calmar Ratio (CAGR / MaxDD) while cutting Drawdown  

---

## 1. Executive Summary & Legacy MIP Baseline Comparison

| Strategy Setting | Full CAGR | Full Max DD | Full Calmar | Full Sharpe | Test OOS CAGR | Test OOS Max DD | Test OOS Calmar |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Legacy MIP Baseline** | 35.01% | 41.65% | **0.84** | 1.01 | 49.98% | 27.34% | **1.83** |
| **Rank 1: Top-10 Buffer-40 Cap-1 (ResMom)** | **32.22%** | **17.71%** | **1.82** | **1.17** | **39.43%** | **13.91%** | **2.83** |
| **Rank 2: Top-10 Buffer-40 Cap-1 (ResMom)** | **32.22%** | **17.71%** | **1.82** | **1.17** | **39.43%** | **13.91%** | **2.83** |
| **Rank 3: Top-10 Buffer-40 Cap-1 (ResMom)** | **32.22%** | **17.71%** | **1.82** | **1.17** | **39.43%** | **13.91%** | **2.83** |

---

## 2. Deep Dive: Top 3 Verified Settings

### 🥇 Top Setting #1: High-Calmar Low-Drawdown Optimizer

#### Complete Configuration Specification:
- **Rebalance Schedule:** `monthly`
- **Portfolio Concentration (Top N):** `10` holdings
- **Momentum Lookback:** `189 trading days`
- **Trend Filter EMA:** `150 days`
- **Exit Buffer Cutoff:** `Rank 40`
- **Sector Hard Cap:** `Max 1 scrips per sector`
- **Position Sizing Mode:** `atr_risk_parity`
- **Benchmark Regime Gate (20 EMA):** `ACTIVE`
- **Idiosyncratic Residual Momentum:** `ACTIVE`

#### Performance & Walk-Forward Audit Matrix:
| Metric | TRAIN (2016–2022) | TEST / OOS (2023–2026) | FULL SAMPLE (2016–2026) | vs Legacy MIP Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **CAGR** | 29.37% | 39.43% | **32.22%** | **-2.79%** |
| **Max Drawdown** | 17.71% | 13.91% | **17.71%** | **-23.94% (Drawdown Cut!)** |
| **Calmar Ratio** | 1.66 | 2.83 | **1.82** | **+0.98x** |
| **Sharpe Ratio** | 1.04 | 1.52 | **1.17** | +0.16 |
| **Sortino Ratio** | 1.7 | 3.13 | **2.05** | +0.46 |
| **Win Rate** | 50.5% | 58.7% | **52.5%** | -
| **Profit Factor** | 2.85 | 2.48 | **2.58** | -
| **Total Trades** | 206 | 104 | **316** | -
| **Final Equity** | ₹5,740,900 | ₹3,308,394 | **₹18,608,442** | +₹-4,554,638 |

### 🥇 Top Setting #2: High-Calmar Low-Drawdown Optimizer

#### Complete Configuration Specification:
- **Rebalance Schedule:** `monthly`
- **Portfolio Concentration (Top N):** `10` holdings
- **Momentum Lookback:** `189 trading days`
- **Trend Filter EMA:** `200 days`
- **Exit Buffer Cutoff:** `Rank 40`
- **Sector Hard Cap:** `Max 1 scrips per sector`
- **Position Sizing Mode:** `atr_risk_parity`
- **Benchmark Regime Gate (20 EMA):** `ACTIVE`
- **Idiosyncratic Residual Momentum:** `ACTIVE`

#### Performance & Walk-Forward Audit Matrix:
| Metric | TRAIN (2016–2022) | TEST / OOS (2023–2026) | FULL SAMPLE (2016–2026) | vs Legacy MIP Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **CAGR** | 29.37% | 39.43% | **32.22%** | **-2.79%** |
| **Max Drawdown** | 17.71% | 13.91% | **17.71%** | **-23.94% (Drawdown Cut!)** |
| **Calmar Ratio** | 1.66 | 2.83 | **1.82** | **+0.98x** |
| **Sharpe Ratio** | 1.04 | 1.52 | **1.17** | +0.16 |
| **Sortino Ratio** | 1.7 | 3.13 | **2.05** | +0.46 |
| **Win Rate** | 50.5% | 58.7% | **52.5%** | -
| **Profit Factor** | 2.85 | 2.48 | **2.58** | -
| **Total Trades** | 206 | 104 | **316** | -
| **Final Equity** | ₹5,740,900 | ₹3,308,394 | **₹18,608,442** | +₹-4,554,638 |

### 🥇 Top Setting #3: High-Calmar Low-Drawdown Optimizer

#### Complete Configuration Specification:
- **Rebalance Schedule:** `monthly`
- **Portfolio Concentration (Top N):** `10` holdings
- **Momentum Lookback:** `252 trading days`
- **Trend Filter EMA:** `150 days`
- **Exit Buffer Cutoff:** `Rank 40`
- **Sector Hard Cap:** `Max 1 scrips per sector`
- **Position Sizing Mode:** `atr_risk_parity`
- **Benchmark Regime Gate (20 EMA):** `ACTIVE`
- **Idiosyncratic Residual Momentum:** `ACTIVE`

#### Performance & Walk-Forward Audit Matrix:
| Metric | TRAIN (2016–2022) | TEST / OOS (2023–2026) | FULL SAMPLE (2016–2026) | vs Legacy MIP Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **CAGR** | 29.37% | 39.43% | **32.22%** | **-2.79%** |
| **Max Drawdown** | 17.71% | 13.91% | **17.71%** | **-23.94% (Drawdown Cut!)** |
| **Calmar Ratio** | 1.66 | 2.83 | **1.82** | **+0.98x** |
| **Sharpe Ratio** | 1.04 | 1.52 | **1.17** | +0.16 |
| **Sortino Ratio** | 1.7 | 3.13 | **2.05** | +0.46 |
| **Win Rate** | 50.5% | 58.7% | **52.5%** | -
| **Profit Factor** | 2.85 | 2.48 | **2.58** | -
| **Total Trades** | 206 | 104 | **316** | -
| **Final Equity** | ₹5,740,900 | ₹3,308,394 | **₹18,608,442** | +₹-4,554,638 |

---

## 3. Top 20 Configurations Ranked by Calmar Ratio (CAGR / MaxDD)

| Rank | Schedule | Top N | Lookback | EMA | Buffer | Sector Cap | Sizing | Regime | Res Mom | Calmar | CAGR | Max DD | Sharpe | Trades |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | monthly | 10 | 189d | 150d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 2 | monthly | 10 | 189d | 200d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 3 | monthly | 10 | 252d | 150d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 4 | monthly | 10 | 252d | 200d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 5 | monthly | 10 | 315d | 150d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 6 | monthly | 10 | 315d | 200d | 40 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.82** | **32.22%** | **17.71%** | 1.17 | 316 |
| 7 | monthly | 10 | 189d | 150d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 8 | monthly | 10 | 189d | 200d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 9 | monthly | 10 | 252d | 150d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 10 | monthly | 10 | 252d | 200d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 11 | monthly | 10 | 315d | 150d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 12 | monthly | 10 | 315d | 200d | 60 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.76** | **32.28%** | **18.34%** | 1.19 | 276 |
| 13 | monthly | 10 | 189d | 150d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 14 | monthly | 10 | 189d | 200d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 15 | monthly | 10 | 252d | 150d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 16 | monthly | 10 | 252d | 200d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 17 | monthly | 10 | 315d | 150d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 18 | monthly | 10 | 315d | 200d | 30 | 1 | `atr_risk_parity` | `ON` | `ON` | **1.7** | **31.53%** | **18.55%** | 1.12 | 355 |
| 19 | monthly | 10 | 189d | 150d | 30 | 1 | `equal_weight` | `ON` | `ON` | **1.67** | **32.24%** | **19.34%** | 1.1 | 355 |
| 20 | monthly | 10 | 189d | 200d | 30 | 1 | `equal_weight` | `ON` | `ON` | **1.67** | **32.24%** | **19.34%** | 1.1 | 355 |
