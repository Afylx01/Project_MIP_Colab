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

### 5-Cell Cloud Workflow:
- **Cell 1:** Environment probe & repository initialization.
- **Cell 2:** Google Drive sync & fast local NVMe database staging.
- **Cell 3:** Multi-architecture C99 SIMD kernel compilation & hardware benchmark sweep.
- **Cell 4:** Interactive IPyWidgets UI cockpit (sliders, dropdowns, Matplotlib momentum charts).
- **Cell 5:** Headless CLI execution.

For detailed instructions on sharing and using Google Cloud Service Accounts without leaking `.json` keys, see [docs/COLAB_SETUP_GUIDE.md](docs/COLAB_SETUP_GUIDE.md).

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
