# Analysis Evidence Index — 2026-10-23

Raw artifacts backing `reports/CODEBASE_DEEP_ANALYSIS.md` and the published dashboard.
All files were generated against the working tree at HEAD `85c78e2` (+19 modified files).

| File | What it proves | Produced by |
|---|---|---|
| `01_data_static.json` | Bar/symbol/date counts, integrity, duplicates, nulls, delisting counts, strategy fingerprint, file hashes | Direct SQLite + SHA-256 queries |
| `02_scan.json` | Full scanner output: 20 picks, factors, regime, breadth, reason codes, coverage | `PydroidScanner.run_scan(as_of_date="2026-10-19", universe_mode="NIFTY500")` |
| `03_factor_recompute.json` | Independent recomputation of Volar, Ret-252, 52w high, ATR-14, stop for top 10 | Separate pandas implementation, no scanner imports |
| `04_backtest.json` | **Canonical NIFTY500** production backtest metrics, monthly returns (30.01% CAGR, 604 trades; **regenerated post-fix**) | `canonical_backtest.py` → `LightweightBacktester.run(2016-01-01 → 2026-08-31, top20, buffer40, cap2, ATR, universe=NIFTY500)` |
| `04b_backtest_all.json` | ALL-symbol reference run (29.59% CAGR, 703 trades), retained for comparison | Previous canonical run (ALL, 1,039 symbols) |
| `05_ledger_audit.json` | Ledger identity audit over the canonical 604-trade NIFTY500 log: whole shares, chronology, PnL, frictions, compounding, CAGR/DD/Sharpe identities | `audit_ledger.py` replay of `reports/trade_log.csv` |
| `06_c_engine_nifty750.json` | Native kernel baseline (NIFTY750 cube) + cube/sim timing | `BruteForceCampaignRunner.run_baseline()` |
| `06b_c_engine_nifty500.log` | Native kernel NIFTY500 result (28.60% CAGR, 38.32% MaxDD, 602 trades) | `run_custom_backtest(universe_name="NIFTY500")` |
| `07_sweep_960.json` | 960-config sweep: 1/2/4/8-thread throughput, distinct signatures, NaNs, best config | Native `execute_sweep` on a 501×4,890 cube |
| `08_universes.json` | All 36 index universes resolve (counts + status) | `ConstituentReconciliationEngine` |
| `09_pytest_full.log` | 565 passed, 6 skipped, 0 failed in 850.28s | `python3 -m pytest -q` |
| `10_backtest_run.log` | Console log of the canonical backtest restore run | `LightweightBacktester` (final run) |
| `11_pipeline_run.log` | End-to-end institutional pipeline: health 7/7, 10 candidates, risk, liquidity, compliance 6/6, tearsheet, 14-sheet workbook, 4.67MB bundle | `scripts/dispatch_institutional_pipeline.py` |
| `12_legacy_ablation_reproduction.log` | Legacy baseline reproduced: 36.80% CAGR, 1.03 Sharpe, −49.74% MaxDD, ₹28,264,374.69 | `LightweightBacktester` equal-weight, no regime, no cap |
| `13_determinism.log` | Two independent scans produce identical pick-table SHA-256 | `PydroidScanner` twice |
| `14_scan_run.log` | Plain scan console log (funnel, timings) | `PydroidScanner` |
| `15_modules_analytics_nextgen_cache.json` | Direct verification of risk suite (15 identities), Brinson single/multi-period, liquidity, residual momentum, vol targeting, delivery flow, cache, cloud sync (**post-fix**) | `verify_modules.py` |
| `15b_modules_run.log` | Console log of the module harness | `verify_modules.py` |
| `16_db_gzip_roundtrip.log` | 352,288,768 B → 106,171,198 B (69.86% saved), 3.3 s decompress, SHA-256 match | `scripts.cloud_sync.compress_file/decompress_file` |
| `17_cli_db_audit.log` | CLI `--option 12`: 16 invariants pass, 12.81 s, exit 0 | `main.py` |
| `18_telegram_chunker.json` | Chunker edge cases after fix: long single line and `<pre>` block split under 4,000 chars (**fixed**) | `core.telegram_sender._chunk_message` |
| `verify_modules.py` | Re-runnable harness that regenerates 15 (analytics, next-gen, cache, cloud sync); writes `/tmp/mip_modules_evidence.json` | `python3 reports/analysis_evidence/verify_modules.py` |
| `20_optimization_grid_summary.json` | IS/OOS selection results from the 8,000-config grid (best by Calmar, Sharpe, CAGR, drawdown-constrained) | `optimize_strategy.py` |
| `21_strategy_validation.json` | Shortlist validation: exact monthly NAVs, costs, crises, bootstrap, PSR/DSR, alpha/beta. **Strategy and benchmark share the same base rebalance; every window records `aligned=true`.** ATR sizing is real (not silently equal-weight). | `validate_candidates.py` |
| `22_candidate_engine_summaries.json` | Engine-level summaries (continuous runs, daily drawdown, trade counts) for the five shortlisted profiles | `summarize_candidates.py` → `runner.run_custom_backtest` |
| `33_reconciliation.json` | Single (engine, universe, config) table; §5.5-vs-§9D mechanism; stress-window labels; survivorship estimate | `reconcile_engines.py` |
| `33b_random_window_quality.json` | VALID / DATA_INSUFFICIENT label for every random window, plus all-window vs valid-only medians | `label_random_windows.py` |
| `34_python_canonical.json` | Python production engine on NIFTY500 (30.01%) and ALL (29.59%) | `reconcile_engines.py` |
| `23_optimization_grid.csv` | Full 8,000-row joined grid with IS and OOS metrics per configuration | `optimize_strategy.py` |
| `24_random_windows.csv` | 200 random 2–5 year windows for the recommended profile | `random_robustness.py` |
| `25_random_perturbations.csv` | 500 random parameter perturbations, IS/OOS | `random_robustness.py` |
| `26_random_costs.csv` | 200 random friction/slippage regimes | `random_robustness.py` |
| `27_monthly_returns.csv` | Monthly strategy vs benchmark returns used for regime/bootstrap tests | `validate_candidates.py` |
| `28_low_dd_grid.csv` | Low-drawdown optimization grid (vol targeting on/off, cap, top-N, buffer) | `random_robustness.py` |
| `29_random_robustness.json` | Consolidated results of all random tests and low-DD selections | `random_robustness.py` |
| `optimize_strategy.py` | Re-runnable IS/OOS 8,000-config optimizer | `python3 reports/analysis_evidence/optimize_strategy.py` |
| `validate_candidates.py` | Re-runnable shortlist validator | `python3 reports/analysis_evidence/validate_candidates.py` |
| `30_low_dd_validation.json` | Exact monthly validation of six low-drawdown profiles | `validate_low_dd.py` |
| `31_random_universes.json/.csv` | **RETRACTED** — no generator exists under this tag | — |
| `32_random_selection_control.json/.csv` | **RETRACTED** — no generator exists under this tag | — |
| `random_robustness.py` | Re-runnable random windows / perturbations / costs / regimes / low-DD grid. Window ends use calendar month offsets; drawdown signs are normalized before filtering | `python3 reports/analysis_evidence/random_robustness.py` |
| `canonical_backtest.py` | Regenerates the canonical NIFTY500 run, `04`, `05`, `trade_log.csv` | `python3 reports/analysis_evidence/canonical_backtest.py` |
| `audit_ledger.py` | Independent ledger replay (PnL, return, friction, compounding, calendar, zero-volume checks) | `python3 .../audit_ledger.py <trade_log> <results> <out>` |
| `summarize_candidates.py` | Regenerates `22` from continuous C-kernel runs | `python3 .../summarize_candidates.py` |
| `reconcile_engines.py` | Regenerates `33` and `reports/ENGINE_RECONCILIATION.md`; runs the survivor/all survivorship control | `python3 .../reconcile_engines.py` |
| `label_random_windows.py` | Labels every random window and recomputes valid-only medians into `33b` | `python3 .../label_random_windows.py` |
| `random_analysis.py` | Corrected random-window analysis (calendar-month windows, DD sign) | `python3 reports/analysis_evidence/random_analysis.py` |
| `validate_low_dd.py` | Re-runnable low-drawdown shortlist validator | `python3 reports/analysis_evidence/validate_low_dd.py` |

Note: `tests/test_backtest_monthly_returns.py` writes to `reports/` and can overwrite
`04_backtest.json`'s on-disk counterparts (`trade_log.csv`, `backtest_results.json`).
The canonical artifacts were regenerated last, after the test suite finished.
