# Project MIP — Institutional Momentum Trading Desk & Platform
### Standalone Zero-Compiler Edition • Python 3.10+ • ARM64 NEON & x86_64 AVX2

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/Afylx01/Project_MIP_Colab/blob/main/notebooks/Project_MIP_Colab.ipynb)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hardware](https://img.shields.io/badge/Snapdragon-8_Gen_2_%7C_x86__64_Cloud-brightgreen.svg)]()

Standalone institutional-grade quantitative momentum workstation engineered for **Google Colab (x86_64 Cloud)**, **Pydroid 3 (Android ARM64 Snapdragon 8 Gen 2)**, and **Linux/macOS High-Performance Workstations**.

---

## ⚡ Key Capabilities

1. **Latest Actual Trading Day EOD Guarantee:**
   - Evaluates real-time IST clock and exchange publish thresholds (>18:30 IST).
   - Automatically cross-references authoritative `data/trading_calendar.txt` and statutory exchange holidays.
   - Guarantees scans execute strictly on the true completed market session with zero silent stale bypasses.
2. **Multi-Architecture C99 SIMD Parallel Acceleration:**
   - **Google Colab (x86_64):** Dynamic compilation with `-march=native -mavx2 -mfma -O3`.
   - **Android S23 (ARM64):** Hand-tuned NEON vector intrinsics with `-march=armv8.2-a+fp16 -O3`.
   - Single 10-year backtest executes in **<40 milliseconds**; sweeps evaluate >800 configurations per second.
3. **Full 36 Official NIFTY Universes:**
   - 15 Broad Market, 14 Sectoral, and 7 Thematic universes with official constituent reconciliation and 30-day cache refresh TTL policy.
4. **Zero-Leak Cloud Staging:**
   - High-speed NVMe staging for `universe.db` (351 MB) circumvents the 40x Google Drive FUSE latency bottleneck.
   - Seamless authentication via Google Colab native Secrets Manager (`GDRIVE_SA_KEY`) or interactive Drive mount, ensuring 0 credential leakage in public repositories.

---

## 🚀 One-Click Cloud Execution (Google Colab)

Click the **Open in Colab** badge above or open [`notebooks/Project_MIP_Colab.ipynb`](notebooks/Project_MIP_Colab.ipynb).

### 4-Cell Cloud Workflow:
- **Cell 1:** Environment probe, Git sync, Drive mount & fast NVMe database staging (with zero-friction public database auto-download).
- **Cell 2:** Interactive IPyWidgets Screener Dashboard & Tearsheet Generator (with SQLite auto-update audit banner and Excel auto-download).
- **Cell 3:** High-Performance C99 SIMD Backtesting & Parallel Brute Force Cockpit (custom date backtests, era presets, sensitivity charts, and parallel sweeps).
- **Cell 4:** Headless CLI Execution Examples.

For detailed instructions on sharing and using Google Cloud Service Accounts without leaking `.json` keys, see [docs/COLAB_SETUP_GUIDE.md](docs/COLAB_SETUP_GUIDE.md).

---

## 💾 Pre-Compiled Universe Database (`universe.db`)

The platform operates on a validated institutional SQLite database (351 MB, 2.16M OHLCV bars across 1,082 NSE symbols from 2007 to present with complete point-in-time corporate action adjustments).
- **Direct Google Drive Link:** [Download universe.db](https://drive.google.com/file/d/1mnaMfODbDwcdyG5NyQrLCunWKwYir1aT/view?usp=sharing)
- **One-Command CLI Download:**
  ```bash
  gdown --id 1mnaMfODbDwcdyG5NyQrLCunWKwYir1aT -O data/universe.db
  ```
When running in Google Colab, Cell 1 automatically checks and downloads this verified database directly into local NVMe storage if not already present.

---

## 📱 Mobile Execution (Pydroid 3 / Android S23)

Run directly from Pydroid 3 or Termux:
```bash
python main.py
```
Or dispatch specific workflows directly via CLI:
```bash
# 1. Weekly Momentum Scan on NIFTY 500
python main.py --option 1 --universe NIFTY500

# 2. Batch Scan across all 36 NIFTY Indices
python main.py --scan-all-universes

# 3. Blazing Fast Brute Force Baseline Simulation
python main.py --brute-force --brute-force-mode baseline

# 4. Multi-Schedule Rebalance Sweep
python main.py --brute-force --brute-force-mode tier1
```

---

## 🔒 Security & Zero-Leak Governance

This repository strictly enforces institutional secret isolation:
- No `.env` or service account keys are stored or committed.
- Copy `.env.example` to `.env` for local configuration.
- Database `universe.db` is provisioned separately from Google Drive and ignored in `.gitignore`.

---

## 📜 Scientific Validation & Testing

Run the comprehensive institutional contract test suite:
```bash
python tests/run_all_tests.py
```
All algorithmic and accounting invariants (cash conservation, weight normalization, 252-bar anti-IPO gate, sector concentration caps) are verified fail-closed.
