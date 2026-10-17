# Changelog

All notable changes, fixes, and quantitative upgrades to **Project MIP (Colab & Headless Quantitative Engine)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.0] - 2026-10-17

### Added
- **Universal Benchmark Selection Across Scanner, Backtester & Brute Force Engine**:
  - Full manual selection freedom for benchmarks across all operational modes:
    - **Scanner**: Computes relative strength (RS-200), market regime (Close vs 20 EMA), and idiosyncratic residual momentum against the selected benchmark index or symbol.
    - **Backtester**: Compares equity curves, calculates relative alpha, beta, and information ratio against the selected benchmark.
    - **Parallel Brute Force Sweeps**: Dynamically generates TensorCubes aligned with the selected benchmark and evaluates market regime cash shields.
  - Complete catalog of supported benchmarks (`core/benchmark_validator.py`):
    - Frontline & Broad Market: `NIFTY500` (Default), `NIFTY50`, `NIFTY750`, `NIFTYNEXT50`, `NIFTYMIDCAP150`, `NIFTYSMALLCAP250`.
    - Sectoral Indices: `NIFTYBANK`, `NIFTYIT`.
    - Dynamic Proxies: `UNIVERSE_PROXY` (Equal-weighted universe median proxy).
    - Constituent Equities: Any individual liquid ticker symbol from `universe.db` (e.g. `RELIANCE`, `TCS`, `HDFCBANK`).
  - Unified benchmark architecture: Catalog, display options, Yahoo continuous chart fetching, and robust indicator calculations integrated into `core/benchmark_validator.py`, preserving the strict 25-module core architecture invariant.
  - CLI parser integration: `--benchmark` parameter supported across `main.py` Options [1], [5], and [18].
  - Interactive Colab UI: Dropdowns for benchmark selection added in both Mode 1 (Backtester) and Mode 2 (Brute Force Sweep) of `colab/dashboard.py`.
  - Dedicated TDD contract suite: `tests/test_benchmark_selection.py` (7 tests, 100% passed).

### Fixed & Improved
- **Chunked Streaming Execution & Real-Time Throughput Telemetry for Massive Sweeps**:
  - Fixed apparent UI freezes during massive brute-force sweeps (e.g. 250,000 or 1,000,000 runs) where no progress was rendered.
  - Sweeps are now dispatched in deterministic streaming chunks (25,000 configurations per batch) with real-time telemetry:
    - Current processed count and total count.
    - Live throughput (`configurations/sec`).
    - Elapsed runtime and estimated time remaining (ETA countdown).
    - Real-time `ipywidgets.IntProgress` bar and label updates in Colab notebook.
- **Dynamic Interactive UI Cockpit for Matrix Presets vs Custom Sweeps**:
  - Automatically hides redundant `Start Date`, `End Date`, and `Schedule` input fields when running matrix presets (which intrinsically define their own dates, multi-era schedules, or random sub-period duration windows).
  - Replaces redundant controls with an informative **Matrix Preset Card** explaining the pre-configured parameters and random horizon sampling.
  - Seamlessly re-displays full date and schedule controls when switching back to `Custom Parameter Sweep`.

## [2.2.0] - 2026-10-17

### Added
- **Modular `colab` Package & Minimal, Clutter-Free Notebook Architecture**:
  - Extracted all bulky orchestration, UI rendering, tearsheet formatting, matplotlib plotting, and widget event handlers out of `Project_MIP_Colab.ipynb` into a dedicated modular package (`colab/`):
    - `colab/environment.py`: `setup_colab_environment()` handles environment probing, drive mounting, NVMe staging, and storage latency benchmarking.
    - `colab/screener.py`: `run_screener_view()` handles live momentum screening, Next-Gen alpha overlay notes, base64 chart rendering, and collapsible HTML tearsheets.
    - `colab/dashboard.py`: `render_backtest_dashboard()` packages the entire 450-line interactive IPyWidgets backtesting & parallel brute force sweep dashboard into a single 1-line call.
  - Reduced notebook code cell volume by **91%** (from 762 lines down to 73 clean lines).
  - Dedicated TDD contract suite: `tests/test_colab_package.py` (5 tests, 100% passed).
- **Random Time Duration Dimension (Monte Carlo Sub-Period Horizon Sweeping)**:
  - Added the **10th Dimension** to the Factorial Matrix Search Space: `generate_random_time_duration_windows()` in `brute_force/grid.py`.
  - Evaluates parameter sets across randomized multi-year horizons (1y, 2y, 3y, 5y, 7y, 10y, Full 18y) to eliminate regime-specific survivorship bias.
  - Multiplies the factorial search space from 1.728M to up to **13,824,000 distinct configurations** ($5 \times 6 \times 4 \times 5 \times 6 \times 6 \times 5 \times 2 \times 8 \times 8$).
  - Added new duration presets:
    - `Tier 3: Factorial + Random Time Durations (Deep - 10,000 runs)` (`--brute-force-mode tier3_deep_durations`)
    - `Tier 3: Factorial + Random Time Durations (Mega - 250,000 runs)` (`--brute-force-mode tier3_mega_durations`)
    - `Tier 3: Factorial + Random Time Durations (Ultra - 1,000,000 runs)` (`--brute-force-mode tier3_ultra_durations`)
  - Added CLI flags `--include-random-durations` / `--random-time-durations` and `--num-random-durations` in `main.py`.
  - Integrated `Random Time Durations Dimension 🎲` toggle and dropdown options into Cell 3 of `Project_MIP_Colab.ipynb`.
  - Dedicated TDD contract suite: 3 new tests in `tests/test_main_brute_force.py` (11/11 passed).
- **Massive Factorial Hyperparameter Grid Engine (1.728M Combinations & Mega/Ultra Presets)**:
  - Expanded Tier 3 parameter search space to evaluate up to **1,728,000 distinct configurations** ($5_{\text{Schedules}} \times 6_{\text{TopN}} \times 4_{\text{Lookback}} \times 5_{\text{EMA}} \times 6_{\text{Buffer}} \times 6_{\text{Retrace}} \times 5_{\text{Sector}} \times 2_{\text{Sizing}} \times 8_{\text{Alphas}}$).
  - Implemented $O(1)$ high-speed indexed sampling (`random.sample(range(total), sample_size)` with flat integer modulo decomposition), generating 250k or 1M parameter sets instantly without Python list allocation overhead.
  - Added new presets:
    - `Tier 3: Mega Factorial Matrix (250,000 runs)` (`--brute-force-mode tier3_mega`)
    - `Tier 3: Ultra Factorial Matrix (1,000,000 runs)` (`--brute-force-mode tier3_ultra`)
  - Supported in both CLI (`main.py`) and the interactive Colab Notebook (`notebooks/Project_MIP_Colab.ipynb`).
- **Optional Alpha Overlays in Brute Force & Parameter Sweeps**:
  - Integrated `use_residual_momentum`, `use_vol_targeting`, and `use_delivery_veto` as optional toggles and full 3-bit permutation sweeps ($2^3 = 8$ states) across baseline, grid, and custom sweep runners.
  - Added CLI flags `--use-residual-momentum`, `--use-vol-targeting`, and `--use-delivery-veto` for brute-force execution.
- **Interactive UI Cockpit Restoration in Cell 3**:
  - Reverted Cell 3 in `notebooks/Project_MIP_Colab.ipynb` to the interactive `ipywidgets` dashboard ("run cell then select"), eliminating Google Colab Form auto-run constraints.
  - Added dropdown options and alpha checkboxes for interactive parameter exploration.
- **Idiosyncratic Residual Momentum in Screener (`use_residual_momentum`)**:
  - Fully integrated into `core/scanner.py`, `scripts/scanner_hardening.py`, and `main.py` CLI parser (`--use-residual-momentum`).
  - Added interactive `#@param {type:"boolean"}` toggle in **Cell 2: Live Momentum Screener Cockpit** of `Project_MIP_Colab.ipynb`.
  - Academic formulation: Blitz, Baltussen & van Vliet (2020) / Robeco idiosyncratic alpha model regressing stock returns against market benchmark returns ($R_{i,t} = \alpha_i + \beta_i R_{m,t} + \epsilon_{i,t}$).
  - 21-day short-term reversal guard: Excludes recent $t-21$ to $t$ sessions to prevent buying exhaustion pumps.
  - Standardized Sharpe scoring: Ranks candidates on risk-adjusted residual return ($\frac{\sum \epsilon_i}{\sigma(\epsilon_i) \cdot \sqrt{231}}$).
  - Composite Momentum Score: Blends 40% canonical Volar + 60% idiosyncratic residual momentum, prioritizing pure company alpha over market beta.
  - Dedicated TDD contract suite: `tests/test_scanner_residual_momentum.py` (4 tests, 100% passed).

### Fixed
- **Latest Expected EOD Date Resolution (DEF-C03)**:
  - Fixed `core/data_engine.py:get_expected_latest_eod()` which was previously capped at the end of the static trading calendar (2026-10-15).
  - Added dynamic weekday and statutory NSE exchange holiday progression logic. The scanner now automatically evaluates and resolves Friday 2026-10-16 on Saturday 2026-10-17.
- **Benchmark Series Continuity & Pre-2020 Equity Curve Collapse (DEF-C04)**:
  - Fixed `brute_force/cube_builder.py:TensorCubeContainer` and `brute_force/runner.py:BruteForceCampaignRunner`.
  - Replaced the unlisted symbol 0 proxy (`360ONE`, listed in September 2019) with true canonical NIFTY 500 benchmark closes (`data/benchmark_nifty500.csv`).
  - Eliminated the artificial -99.9% pre-2019 drawdown and 1,200x equity scaling distortion; backtest equity and drawdown curves now render continuously from 2010 to 2026.
- **Constituent Engine Universe `ALL` Resolution (DEF-C01)**:
  - Eliminated `BLOCKED` status when scanning universe `ALL` in `scripts/scanner_hardening.py` by resolving active universe tickers directly from SQLite prices table.
- **Benchmark Staleness Recovery (DEF-C02)**:
  - Added resilient benchmark synchronization and forward-fill recovery for Relative Strength (RS) ratio calculation when `allow_stale_data=True`, preventing 0 candidate picks.
- **Pandas `Series.pct_change` FutureWarning (DEF-C05)**:
  - Added explicit `fill_method=None` and upstream `.ffill()` across calculation engines.
- **SIMD Simulation Kernel Loop Boundary (DEF-C06)**:
  - Corrected loop condition in `brute_force/sim_kernel.c` from `r < r_end` to `r <= r_end`, guaranteeing execution of the final rebalance session matching `end_session = sched_indices[r_end]`.
- **Corporate Action Event Adjustment Factor Alias (DEF-C07)**:
  - Added `@property adjustment_factor` to `CorporateActionEvent` in `core/analytical_price.py`.

---

## [2.1.0] - 2026-10-16

### Fixed
- **Bugs Colab Remediation (DEF-C01 to DEF-C07)**:
  - Full reproducible TDD proof suite in `tests/test_bugs_colab_proof.py`.
  - Recompiled high-performance C99 SIMD simulation kernel with updated bounds.
  - Reconciled trading calendar and corporate actions pipeline.
  - Published comprehensive Evidence Package and Proof Register in `reports/EVIDENCE_PACKAGE_BUGS_COLAB.md`.

---

## [2.0.0] - 2026-10-15

### Added
- **Google Colab Cloud Architecture**:
  - Zero-leak standalone repository topology in `Project_MIP_Colab`.
  - Multi-architecture C99 compiler bridge supporting both x86_64 AVX2 / AVX-512 (Google Colab) and ARM64 NEON (Android S23 / Snapdragon 8 Gen 2).
  - High-speed NVMe staging layer (`scripts/cloud_sync.py`) eliminating Google Drive FUSE latency penalties.
  - 5-cell interactive Jupyter Notebook `notebooks/Project_MIP_Colab.ipynb` with Colab Form sliders, IPyWidgets dashboard, and automatic browser downloads.
- **Next-Gen Institutional Alpha Overlays**:
  - Feature 1: `nextgen/residual_momentum.py` (Blitz residual momentum factor engine).
  - Feature 2: `nextgen/vector_engine.py` (2D contiguous matrix analytical acceleration).
  - Feature 3: `nextgen/volatility_targeting.py` (Continuous EWMA realized volatility targeting and Dynamic Cash Shield).
  - Feature 4: `nextgen/delivery_flow.py` (Close Location Value and Smart Money Flow Index institutional distribution veto).

### Fixed
- **Institutional Codebase Vulnerability Remediation (DEF-01 through DEF-22)**:
  - DEF-01: Split/bonus price adjustment in backtester eliminates artificial -50% to -90% crashes.
  - DEF-02: `MAX_UNIVERSE_SYMBOLS` expanded from 1024 to 2048 in `sim_kernel.c` eliminating stack smashing on `ALL`.
  - DEF-03: Dynamic tensor axis resolution in `nextgen_sim.py` correcting 200 EMA lookup.
  - DEF-04: Persistent session state ledger in `schedule_production_cron.py` eliminating infinite loop dispatch.
  - DEF-05: Isolation of existing HOLD positions from portfolio rebalance budget in `portfolio.py`.
  - DEF-07: 50% distress liquidation haircut on delisted/suspended tickers.
  - DEF-08: Per-run local counter eliminating pthread race conditions in `sim_kernel.c`.
  - DEF-09: `isnan()` and `isinf()` guards before candidate ingestion in C99 kernel.
  - DEF-10: Immediate `REJECTED` order status assignment on cash exhaustion.
  - DEF-11: Sanitized return arrays with non-finite clamping in `volatility_targeting.py`.
  - DEF-12: Fail-closed buy gate on missing delivery data in `delivery_flow.py`.
  - DEF-13: Vectorized 2D Rolling Residual Momentum reducing computation from 120s to 2.6s.
  - DEF-14: `run_scan()` signature parity across scanner modules.
  - DEF-16: Connection leak eliminated in `_record_picks_history()`.
  - DEF-17: Bidirectional fill for benchmark missing dates in `market_breadth.py`.
  - DEF-21: UUID hex suffixes eliminating temporary file collision in cloud sync.
  - DEF-22: Matplotlib figure leak remediation with guaranteed `plt.close(fig)` cleanup.

---

## [1.0.0] - 2026-10-13

### Added
- **Production Sealed Release**:
  - 25 pure-Python core decoupled modules tracked in `certificates/PROVENANCE_MANIFEST.json`.
  - Immutable production SQLite universe database (`data/universe.db`, 2,164,420 rows, SHA-256 sealed).
  - Institutional production deployment playbook in `docs/PRODUCTION_DEPLOYMENT_PLAYBOOK.md`.
  - Automated smoke verifier `scripts/verify_production_readiness.py`.
  - Cryptographically sealed production readiness certificate `certificates/PRODUCTION_READINESS_CERTIFICATE.json`.
