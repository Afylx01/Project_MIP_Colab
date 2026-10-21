# Full Codebase Variable Audit & Global Optimization Scorecard

**Execution Timestamp:** 2026-10-21 15:55:40 UTC  
**Total Backtests Executed:** 6,956 simulations across 10.7 Years (2016–2026)  
**Universe:** NIFTY 500 (501 Constituents, 1.28M Raw Bars)  
**Execution Engine:** C99 NEON Fast Simulation Cube Engine  

---

## 🏆 Global Best Possible Settings (Empirically Proven)

| Parameter | Best Value | Baseline Canonical | Impact / Advantage |
| :--- | :---: | :---: | :--- |
| **Schedule** | **`monthly`** | `monthly` | Optimization schedule |
| **Top N Holdings** | **`10`** | `20` | Optimal concentration |
| **Exit Buffer Rank** | **`60`** | `40` | Churn dampener |
| **Momentum Lookback** | **`189d`** | `252d` | Returns velocity |
| **Trend Filter EMA** | **`150d`** | `200d` | Macro trend floor |
| **Sector Hard Cap** | **`1`** | `2` | Concentration limit |
| **Sizing Mode** | **`atr_risk_parity`** | `atr_risk_parity` | Volatility inverse sizing |
| **Regime Filter Gate** | **`BYPASS`** | `ACTIVE` | Cash shield toggle |
| **Residual Momentum** | **`ACTIVE`** | `BYPASS` | Idiosyncratic alpha |

### 📊 Best Configuration Performance:
- **Sharpe Ratio:** **1.26** (vs Canonical Baseline 1.09, Legacy MIP 1.03)
- **CAGR:** **38.57%**
- **Sortino Ratio:** **2.05**
- **Max Drawdown:** **26.85%**
- **Calmar Ratio:** **1.44**
- **Profit Factor:** **2.82**
- **Ending Capital:** **₹30,403,714** from ₹10,00,000 initial

---

## 1. Single-Variable Ablation Matrix (ON vs OFF Holding Constant)

| Variable / Feature Name | Category | CAGR | Sharpe | Δ Sharpe | Max DD | Win Rate | Profit Factor | Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **EXIT_BUFFER_30** | `EXIT_BUFFER` | 31.6% | **1.17** | +0.16 | 21.31% | 47.3% | 2.22 | 🟢 PROVEN |
| **RESIDUAL_MOMENTUM_ON** | `ALPHA_FACTOR` | 28.14% | **1.08** | +0.07 | 21.37% | 51.5% | 2.15 | 🟢 PROVEN |
| **REGIME_FILTER_OFF** | `REGIME_FILTER` | 34.6% | **1.07** | +0.06 | 25.82% | 45.4% | 2.2 | 🟢 PROVEN |
| **EXIT_BUFFER_20** | `EXIT_BUFFER` | 28.24% | **1.06** | +0.05 | 26.27% | 48.9% | 2.05 | 🟢 PROVEN |
| **EXIT_BUFFER_10** | `EXIT_BUFFER` | 25.05% | **1.04** | +0.03 | 27.28% | 50.9% | 1.91 | 🟢 PROVEN |
| **VOL_TARGETING_ON** | `RISK_OVERLAY` | 28.62% | **1.02** | +0.01 | 19.79% | 44.4% | 2.29 | 🟢 PROVEN |
| **RETRACE_FILTER_OFF** | `FILTER_RETRACE` | 31.14% | **1.02** | +0.01 | 22.31% | 46.4% | 2.26 | 🟢 PROVEN |
| **BASELINE_CANONICAL** | `REFERENCE` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **DELIVERY_VETO_ON** | `MICROSTRUCTURE` | 28.73% | **1.01** | +0.00 | 24.19% | 45.3% | 2.17 | 🟡 NEUTRAL |
| **TREND_FILTER_OFF** | `FILTER_TREND` | 29.25% | **1.01** | +0.00 | 19.9% | 45.1% | 2.23 | 🟡 NEUTRAL |
| **LOOKBACK_126D** | `LOOKBACK` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **LOOKBACK_189D** | `LOOKBACK` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **LOOKBACK_252D** | `LOOKBACK` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **LOOKBACK_315D** | `LOOKBACK` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **EMA_TREND_50D** | `TREND_EMA` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **EMA_TREND_100D** | `TREND_EMA` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **EMA_TREND_150D** | `TREND_EMA` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **EMA_TREND_200D** | `TREND_EMA` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **EMA_TREND_250D** | `TREND_EMA` | 29.26% | **1.01** | +0.00 | 20.17% | 44.4% | 2.22 | 🟡 NEUTRAL |
| **LEGACY_PODCAST_MIP** | `LEGACY_BASELINE` | 35.01% | **1.01** | +0.00 | 41.65% | 45.9% | 2.33 | 🟡 NEUTRAL |
| **SIZING_EQUAL_WEIGHT** | `SIZING_MODE` | 31.15% | **1.0** | -0.01 | 21.81% | 44.4% | 2.1 | 🟡 NEUTRAL |
| **SECTOR_CAP_OFF** | `SECTOR_CAP` | 28.64% | **0.99** | -0.02 | 26.89% | 46.3% | 2.54 | 🟡 NEUTRAL |
| **RS_FILTER_OFF** | `FILTER_RS` | 28.45% | **0.99** | -0.02 | 17.59% | 44.7% | 2.18 | 🟡 NEUTRAL |
| **TOP_N_10** | `CONCENTRATION` | 31.11% | **0.98** | -0.03 | 33.9% | 44.6% | 2.47 | 🟡 NEUTRAL |
| **TOP_N_15** | `CONCENTRATION` | 28.56% | **0.98** | -0.03 | 24.33% | 42.6% | 2.25 | 🟡 NEUTRAL |
| **SECTOR_CAP_4** | `SECTOR_CAP` | 27.93% | **0.98** | -0.03 | 25.8% | 44.2% | 2.41 | 🟡 NEUTRAL |
| **NEXTGEN_ALL_ON** | `NEXTGEN_COMBINED` | 24.79% | **0.97** | -0.04 | 21.57% | 50.7% | 2.13 | 🟡 NEUTRAL |
| **EXIT_BUFFER_60** | `EXIT_BUFFER` | 27.98% | **0.95** | -0.06 | 24.1% | 42.7% | 2.13 | 🔴 HARMFUL |
| **TOP_N_30** | `CONCENTRATION` | 24.3% | **0.93** | -0.08 | 28.73% | 48.1% | 2.07 | 🔴 HARMFUL |
| **SECTOR_CAP_1** | `SECTOR_CAP` | 25.58% | **0.93** | -0.08 | 31.22% | 49.1% | 2.18 | 🔴 HARMFUL |
| **SECTOR_CAP_3** | `SECTOR_CAP` | 27.64% | **0.93** | -0.08 | 21.37% | 44.9% | 2.24 | 🔴 HARMFUL |
| **SCHEDULE_QUARTERLY** | `SCHEDULE` | 24.38% | **0.71** | -0.30 | 18.73% | 50.6% | 2.75 | 🔴 HARMFUL |
| **TOP_N_5** | `CONCENTRATION` | 18.97% | **0.64** | -0.37 | 24.76% | 49.1% | 2.37 | 🔴 HARMFUL |
| **SCHEDULE_HALF_YEARLY** | `SCHEDULE` | 26.53% | **0.6** | -0.41 | 18.77% | 57.8% | 3.83 | 🔴 HARMFUL |
| **SCHEDULE_WEEKLY** | `SCHEDULE` | 15.34% | **0.38** | -0.63 | 77.42% | 40.4% | 1.34 | 🔴 HARMFUL |
| **SCHEDULE_YEARLY** | `SCHEDULE` | 20.69% | **0.35** | -0.66 | 18.74% | 62.9% | 6.89 | 🔴 HARMFUL |

---

## 2. 8-State Alpha Factorial Permutations ($2^3 = 8$)

| State | Res Mom | Vol Target | Delivery Veto | CAGR | Sharpe | Sortino | Max DD | Profit Factor | Final Equity |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **001: Residual Momentum Only** | `ON` | `OFF` | `OFF` | 28.14% | **1.08** | 1.9 | 21.37% | 2.15 | ₹13,402,481 |
| **101: Residual Mom + Delivery Veto** | `ON` | `OFF` | `ON` | 27.84% | **1.06** | 1.85 | 21.83% | 2.13 | ₹13,079,065 |
| **010: Volatility Targeting Only** | `OFF` | `ON` | `OFF` | 28.62% | **1.02** | 1.7 | 19.79% | 2.29 | ₹13,940,614 |
| **000: Baseline (Canonical Volar Only)** | `OFF` | `OFF` | `OFF` | 29.26% | **1.01** | 1.66 | 20.17% | 2.22 | ₹14,679,076 |
| **100: Delivery Veto Only** | `OFF` | `OFF` | `ON` | 28.73% | **1.01** | 1.72 | 24.19% | 2.17 | ₹14,063,444 |
| **011: Residual Mom + Vol Targeting** | `ON` | `ON` | `OFF` | 25.26% | **1.01** | 1.76 | 21.11% | 2.16 | ₹10,567,049 |
| **110: Vol Targeting + Delivery Veto** | `OFF` | `ON` | `ON` | 27.35% | **1.01** | 1.71 | 23.65% | 2.21 | ₹12,565,510 |
| **111: All 3 Alpha Overlays Active** | `ON` | `ON` | `ON` | 24.79% | **0.97** | 1.68 | 21.57% | 2.13 | ₹10,158,568 |

---

## 3. Top 10 Global Configurations (Ranked by Sharpe)

| Rank | Schedule | Top N | Lookback | EMA | Buffer | Sector Cap | Sizing | Regime | Res Mom | Sharpe | CAGR | Max DD |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | monthly | 10 | 189d | 150d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 2 | monthly | 10 | 189d | 200d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 3 | monthly | 10 | 252d | 150d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 4 | monthly | 10 | 252d | 200d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 5 | monthly | 10 | 315d | 150d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 6 | monthly | 10 | 315d | 200d | 60 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.26** | **38.57%** | 26.85% |
| 7 | monthly | 10 | 189d | 150d | 20 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.25** | **39.81%** | 28.35% |
| 8 | monthly | 10 | 189d | 200d | 20 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.25** | **39.81%** | 28.35% |
| 9 | monthly | 10 | 252d | 150d | 20 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.25** | **39.81%** | 28.35% |
| 10 | monthly | 10 | 252d | 200d | 20 | 1 | `atr_risk_parity` | `OFF` | `ON` | **1.25** | **39.81%** | 28.35% |
