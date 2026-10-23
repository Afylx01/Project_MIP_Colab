# Institutional Empirical Feature Audit & Ablation Scorecard
**Execution Timestamp:** 2026-10-23 06:36:53 UTC
**Data Source:** Real Historical SQLite Database (`data/universe.db`), 1,083 Indian Equities, 2.17M OHLCV bars
**Reference Benchmark:** NIFTY 500 Index (Real Daily Close)
**Evaluation Engine:** LightweightBacktester (t+1 Open, whole shares, Indian statutory friction model)
**Statistics:** EMPIRICAL_DSR_PSR_ACTIVE
**Multiple Testing Trial Family (K):** 9 ablation feature experiments (upstream grid search excluded from ablation family; evaluated independently)

---

## 1. Full Sample Ablation Matrix (2016–2026)
| Rank | Feature / Experiment | Status | CAGR | Sharpe | PSR | DSR | Max DD | Daily Max DD | Win Rate | Profit Factor | Annual Trades | Δ Sharpe | Δ CAGR | Δ Max DD | Final Equity |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **+ ATR Risk Parity Sizing** | `NOT_STATISTICALLY_SIGNIFICANT` | 39.42% | 1.11 | 0.9999 | 0.9897 | -46.37% | -54.87% | 46.0% | 2.34 | 66 | +0.08 | +2.62% | +3.37% | ₹34,598,307 |
| 2 | **+ Full Modern Production Stack** | `NOT_STATISTICALLY_SIGNIFICANT` | 30.35% | 1.09 | 1.0000 | 0.9930 | -23.34% | -34.40% | 45.7% | 2.17 | 66 | +0.06 | -6.45% | +26.40% | ₹16,887,170 |
| 3 | **+ Sector Hard Cap (Max 2)** | `NOT_STATISTICALLY_SIGNIFICANT` | 35.09% | 1.06 | 0.9999 | 0.9858 | -33.71% | -43.54% | 45.6% | 1.94 | 81 | +0.03 | -1.71% | +16.03% | ₹24,712,403 |
| 4 | **- Exit Buffer Removed (Buffer = 20)** | `NOT_STATISTICALLY_SIGNIFICANT` | 37.72% | 1.04 | 0.9998 | 0.9805 | -52.10% | -59.09% | 46.3% | 1.89 | 95 | +0.01 | +0.92% | -2.36% | ₹30,361,331 |
| 5 | **Legacy MIP Baseline** | **[PROVEN_BASELINE]** | 36.80% | 1.03 | 0.9998 | 0.9817 | -49.74% | -57.04% | 46.3% | 2.12 | 66 | 0.00 | 0.00 | 0.00 | ₹28,264,375 |
| 6 | **+ Diversified Breadth (Top 30)** | `NOT_STATISTICALLY_SIGNIFICANT` | 34.31% | 1.00 | 0.9997 | 0.9700 | -42.19% | -51.34% | 46.3% | 2.05 | 91 | -0.03 | -2.49% | +7.55% | ₹23,231,918 |
| 7 | **+ Benchmark 20 EMA Regime Gate** | `NOT_STATISTICALLY_SIGNIFICANT` | 29.13% | 0.95 | 0.9997 | 0.9745 | -40.83% | -49.03% | 44.4% | 2.06 | 55 | -0.08 | -7.67% | +8.91% | ₹15,272,146 |
| 8 | **+ Wide Exit Buffer (Buffer = 60)** | `NOT_STATISTICALLY_SIGNIFICANT` | 33.58% | 0.95 | 0.9997 | 0.9709 | -47.61% | -55.90% | 46.0% | 2.15 | 58 | -0.08 | -3.22% | +2.13% | ₹21,929,795 |
| 9 | **+ High Concentration (Top 10)** | `NOT_STATISTICALLY_SIGNIFICANT` | 34.80% | 0.88 | 0.9995 | 0.9595 | -56.90% | -61.39% | 44.4% | 2.00 | 37 | -0.15 | -2.00% | -7.16% | ₹24,159,432 |

---

## 3. Data-Driven Final Verdict & Actionable Directives
### 🟢 KEEP (Proven Profitable & Core Additive)
- **Legacy MIP Baseline**: Pure unadulterated podcast MIP: Volar, Equal-Weight, Top 20, Buffer 40, Stop 20%, No Regime, No Sector Cap (Sharpe: 1.03, CAGR: 36.80%, ΔSharpe: 0.00)

### ⚪ NOT STATISTICALLY SIGNIFICANT (Policy A: p_bonf ≥ 0.05 or DSR < 0.50)
- **+ Benchmark 20 EMA Regime Gate**: Defensive cash shield: block new entries when NIFTY 500 close < 20 EMA (Sharpe: 0.95, CAGR: 29.13%, ΔSharpe: -0.08, DSR: 0.9745, p_bonf: 1.0)
- **+ Sector Hard Cap (Max 2)**: Max 2 stocks per industry sector to control sector concentration risk (Sharpe: 1.06, CAGR: 35.09%, ΔSharpe: +0.03, DSR: 0.9858, p_bonf: 1.0)
- **+ ATR Risk Parity Sizing**: Size positions inversely to 14-day ATR volatility instead of 1/N equal weight (Sharpe: 1.11, CAGR: 39.42%, ΔSharpe: +0.08, DSR: 0.9897, p_bonf: 1.0)
- **- Exit Buffer Removed (Buffer = 20)**: Strict Top 20: liquidate positions as soon as rank drops below 20 (no buffer) (Sharpe: 1.04, CAGR: 37.72%, ΔSharpe: +0.01, DSR: 0.9805, p_bonf: 1.0)
- **+ Wide Exit Buffer (Buffer = 60)**: Wide retention buffer up to Rank 60 to further dampen turnover churn (Sharpe: 0.95, CAGR: 33.58%, ΔSharpe: -0.08, DSR: 0.9709, p_bonf: 1.0)
- **+ High Concentration (Top 10)**: Concentrated 10-stock portfolio (Top 10, Buffer 20) (Sharpe: 0.88, CAGR: 34.80%, ΔSharpe: -0.15, DSR: 0.9595, p_bonf: 1.0)
- **+ Diversified Breadth (Top 30)**: Diversified 30-stock portfolio (Top 30, Buffer 60) (Sharpe: 1.00, CAGR: 34.31%, ΔSharpe: -0.03, DSR: 0.97, p_bonf: 1.0)
- **+ Full Modern Production Stack**: All institutional guards: Regime Gate + Sector Cap (2) + ATR Sizing + Buffer 40 (Sharpe: 1.09, CAGR: 30.35%, ΔSharpe: +0.06, DSR: 0.993, p_bonf: 1.0)

### 🟡 INVESTIGATE / NEUTRAL (Marginal Alpha / Context-Dependent)

### 🔴 REMOVE / JUST COMPLEXITY (Uncompensated Complexity or Harmful Drag)

### ⚠️ DATA LIMITED / UNTESTABLE IN HISTORICAL SQLITE
- **Delivery Absorption Flow Factor**: `[UNTESTED / DATA LIMITED]` — Traded volume is available in SQLite, but exchange delivery breakout percentage is only captured in recent bhavcopies. Cannot fabricate 10-year delivery data.
- **Zerodha Kite 1-Click Basket**: `[OPERATIONAL BRIDGE]` — UI/execution utility only; zero mathematical effect on strategy returns.
- **3-Tier Command Desk & UserProfile Runner**: `[OPERATIONAL BRIDGE]` — CLI ergonomics & scheduler automation; zero strategy math impact.