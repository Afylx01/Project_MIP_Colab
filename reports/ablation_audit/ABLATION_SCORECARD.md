# Institutional Empirical Feature Audit & Ablation Scorecard
**Execution Timestamp:** 2026-10-21 14:58:25 UTC
**Data Source:** Real Historical SQLite Database (`data/universe.db`), 1,083 Indian Equities, 2.17M OHLCV bars
**Reference Benchmark:** NIFTY 500 Index (Real Daily Close)
**Evaluation Engine:** LightweightBacktester (t+1 Open, whole shares, Indian statutory friction model)

---

## 1. Full Sample Ablation Matrix (2016–2026)
| Rank | Feature / Experiment | Status | CAGR | Sharpe | Max DD | Daily Max DD | Win Rate | Profit Factor | Annual Trades | Δ Sharpe | Δ CAGR | Δ Max DD | Final Equity |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **+ ATR Risk Parity Sizing** | **[PROVEN_PROFITABLE]** | 39.42% | 1.11 | -46.37% | -54.87% | 46.0% | 2.34 | 66 | +0.08 | +2.62% | +3.37% | ₹34,598,307 |
| 2 | **+ Full Modern Production Stack** | `HARMFUL` | 30.35% | 1.09 | -23.34% | -34.40% | 45.7% | 2.17 | 66 | +0.06 | -6.45% | +26.40% | ₹16,887,170 |
| 3 | **+ Sector Hard Cap (Max 2)** | `NEUTRAL` | 35.09% | 1.06 | -33.71% | -43.54% | 45.6% | 1.94 | 81 | +0.03 | -1.71% | +16.03% | ₹24,712,403 |
| 4 | **- Exit Buffer Removed (Buffer = 20)** | `JUST_COMPLEXITY` | 37.72% | 1.04 | -52.10% | -59.09% | 46.3% | 1.89 | 95 | +0.01 | +0.92% | -2.36% | ₹30,361,331 |
| 5 | **Legacy MIP Baseline** | **[PROVEN_BASELINE]** | 36.80% | 1.03 | -49.74% | -57.04% | 46.3% | 2.12 | 66 | 0.00 | 0.00 | 0.00 | ₹28,264,375 |
| 6 | **+ Diversified Breadth (Top 30)** | `NEUTRAL` | 34.31% | 1.00 | -42.19% | -51.34% | 46.3% | 2.05 | 91 | -0.03 | -2.49% | +7.55% | ₹23,231,918 |
| 7 | **+ Benchmark 20 EMA Regime Gate** | `HARMFUL` | 29.13% | 0.95 | -40.83% | -49.03% | 44.4% | 2.06 | 55 | -0.08 | -7.67% | +8.91% | ₹15,272,146 |
| 8 | **+ Wide Exit Buffer (Buffer = 60)** | `NEUTRAL` | 33.58% | 0.95 | -47.61% | -55.90% | 46.0% | 2.15 | 58 | -0.08 | -3.22% | +2.13% | ₹21,929,795 |
| 9 | **+ High Concentration (Top 10)** | `HARMFUL` | 34.80% | 0.88 | -56.90% | -61.39% | 44.4% | 2.00 | 37 | -0.15 | -2.00% | -7.16% | ₹24,159,432 |

---

## 2. Walk-Forward Robustness: In-Sample vs Out-of-Sample
| Feature / Experiment | IS CAGR (2016-2021) | IS Sharpe | OOS CAGR (2022-2026) | OOS Sharpe | OOS Max DD | Overfitting Ratio (OOS/IS) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Legacy MIP Baseline** | 37.79% | 1.01 | 35.86% | 1.07 | -20.85% | **1.06x** |
| **+ Benchmark 20 EMA Regime Gate** | 29.11% | 0.92 | 30.64% | 1.10 | -16.89% | **1.2x** |
| **+ Sector Hard Cap (Max 2)** | 34.20% | 1.02 | 35.13% | 1.06 | -26.43% | **1.04x** |
| **+ ATR Risk Parity Sizing** | 38.72% | 1.05 | 40.38% | 1.21 | -20.96% | **1.15x** |
| **- Exit Buffer Removed (Buffer = 20)** | 36.51% | 0.99 | 39.40% | 1.11 | -22.64% | **1.12x** |
| **+ Wide Exit Buffer (Buffer = 60)** | 36.09% | 0.98 | 31.28% | 0.94 | -22.33% | **0.96x** |
| **+ High Concentration (Top 10)** | 31.12% | 0.76 | 42.37% | 1.12 | -23.12% | **1.47x** |
| **+ Diversified Breadth (Top 30)** | 33.94% | 0.96 | 35.14% | 1.08 | -24.23% | **1.13x** |
| **+ Full Modern Production Stack** | 30.51% | 1.09 | 29.57% | 1.09 | -16.55% | **1.0x** |

---

## 3. Data-Driven Final Verdict & Actionable Directives
### 🟢 KEEP (Proven Profitable & Core Additive)
- **Legacy MIP Baseline**: Pure unadulterated podcast MIP: Volar, Equal-Weight, Top 20, Buffer 40, Stop 20%, No Regime, No Sector Cap (Sharpe: 1.03, CAGR: 36.80%, ΔSharpe: 0.00)
- **+ ATR Risk Parity Sizing**: Size positions inversely to 14-day ATR volatility instead of 1/N equal weight (Sharpe: 1.11, CAGR: 39.42%, ΔSharpe: +0.08)

### 🟡 INVESTIGATE / NEUTRAL (Marginal Alpha / Context-Dependent)
- **+ Sector Hard Cap (Max 2)**: Max 2 stocks per industry sector to control sector concentration risk (Sharpe: 1.06, CAGR: 35.09%, ΔSharpe: +0.03)
- **+ Wide Exit Buffer (Buffer = 60)**: Wide retention buffer up to Rank 60 to further dampen turnover churn (Sharpe: 0.95, CAGR: 33.58%, ΔSharpe: -0.08)
- **+ Diversified Breadth (Top 30)**: Diversified 30-stock portfolio (Top 30, Buffer 60) (Sharpe: 1.00, CAGR: 34.31%, ΔSharpe: -0.03)

### 🔴 REMOVE / JUST COMPLEXITY (Uncompensated Complexity or Harmful Drag)
- **- Exit Buffer Removed (Buffer = 20)** `[JUST COMPLEXITY]`: Strict Top 20: liquidate positions as soon as rank drops below 20 (no buffer) (Sharpe: 1.04, CAGR: 37.72%, ΔSharpe: +0.01, ΔCAGR: +0.92%)
- **+ Benchmark 20 EMA Regime Gate** `[HARMFUL DRAG]`: Defensive cash shield: block new entries when NIFTY 500 close < 20 EMA (Sharpe: 0.95, CAGR: 29.13%, ΔSharpe: -0.08, ΔCAGR: -7.67%)
- **+ High Concentration (Top 10)** `[HARMFUL DRAG]`: Concentrated 10-stock portfolio (Top 10, Buffer 20) (Sharpe: 0.88, CAGR: 34.80%, ΔSharpe: -0.15, ΔCAGR: -2.00%)
- **+ Full Modern Production Stack** `[HARMFUL DRAG]`: All institutional guards: Regime Gate + Sector Cap (2) + ATR Sizing + Buffer 40 (Sharpe: 1.09, CAGR: 30.35%, ΔSharpe: +0.06, ΔCAGR: -6.45%)

### ⚠️ DATA LIMITED / UNTESTABLE IN HISTORICAL SQLITE
- **Delivery Absorption Flow Factor**: `[UNTESTED / DATA LIMITED]` — Traded volume is available in SQLite, but exchange delivery breakout percentage is only captured in recent bhavcopies. Cannot fabricate 10-year delivery data.
- **Zerodha Kite 1-Click Basket**: `[OPERATIONAL BRIDGE]` — UI/execution utility only; zero mathematical effect on strategy returns.
- **3-Tier Command Desk & UserProfile Runner**: `[OPERATIONAL BRIDGE]` — CLI ergonomics & scheduler automation; zero strategy math impact.