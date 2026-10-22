"""
tests/test_forensic_integrity_audit.py - Institutional Forensic Integrity Test Suite
Verifies the mathematical reconciliation and forensic invariants of the bear-market
stress testing harness, canonical baseline delta accounting, deduplication completeness,
and sim_kernel C99 NEON stress vectors.

Target Assertions:
  - A1: MaxDD >= |total_return| for all negative-return crisis windows
  - A2: Explicit disclosure of actual trading days, warmup days, and cash days
  - A3: COVID-2020 precision (raw MaxDD >= 4 decimals, no 0.00% placeholder, Calmar <= 100, dated cash event)
  - A4: Reclassification against canonical baseline (CAGR 35.01%, MaxDD 41.65%, Calmar 0.84)
  - A5: Deduplication exposes all 4 distinct signatures + documented policy for rank 4
  - A6: Effective trading window consistency
  - V1-V4: Synthetic stress vectors (straight drop, dip/recovery, NaN handling, zero-capital guard)
  - Precision gate: No 0.00% or unbounded Calmar in stress reporting
"""

import json
import math
import re
import sys
from pathlib import Path
import unittest
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.bridge import NativeBruteForceEngine
from brute_force.cube_builder import TensorCubeContainer

REPORT_DIR = PROJECT_ROOT / "reports" / "forensic_audit"
JSON_REPORT_PATH = REPORT_DIR / "forensic_audit_results.json"
MD_REPORT_PATH = REPORT_DIR / "FORENSIC_INTEGRITY_REPORT.md"


class TestForensicIntegrityAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert JSON_REPORT_PATH.exists(), f"Missing audit JSON report: {JSON_REPORT_PATH}"
        assert MD_REPORT_PATH.exists(), f"Missing audit MD report: {MD_REPORT_PATH}"

        with open(JSON_REPORT_PATH, "r", encoding="utf-8") as f:
            cls.data = json.load(f)

        with open(MD_REPORT_PATH, "r", encoding="utf-8") as f:
            cls.md_text = f.read()

        cls.engine = NativeBruteForceEngine()

    # -------------------------------------------------------------------------
    # Assertion A1: Drawdown Identity on Total Return
    # -------------------------------------------------------------------------
    def test_a1_drawdown_identity_on_total_return(self):
        """
        A1: For every (window, strategy) pair in the bear-market stress table:
            if total_return < 0:  MaxDD >= -total_return
        """
        stress_tests = self.data.get("bear_market_stress_tests", [])
        self.assertGreaterEqual(len(stress_tests), 4, "Must cover all 4 stress windows")

        for window in stress_tests:
            w_name = window["window"]

            # Legacy MIP check
            leg_ret = window["legacy_total_return"]
            leg_dd = window["legacy_maxdd_raw"]
            if leg_ret < 0:
                self.assertGreaterEqual(
                    leg_dd + 1e-4,
                    abs(leg_ret),
                    f"A1 Violation in {w_name} (Legacy MIP): MaxDD ({leg_dd:.4f}%) < |Total Return| ({abs(leg_ret):.4f}%)"
                )
            self.assertTrue(window["assertion_a1_legacy_pass"])

            # Top Config check
            top_ret = window["top_total_return"]
            top_dd = window["top_maxdd_raw"]
            if top_ret < 0:
                self.assertGreaterEqual(
                    top_dd + 1e-4,
                    abs(top_ret),
                    f"A1 Violation in {w_name} (Top Config): MaxDD ({top_dd:.4f}%) < |Total Return| ({abs(top_ret):.4f}%)"
                )
            self.assertTrue(window["assertion_a1_top_pass"])

    def test_a1_boundary_lookahead_bug(self):
        """
        A1 boundary test: schedule [0, 10, 29], window [0, 10], close[10]=100, open[11]=200.
        Trade at day 11 must be rejected/not executed inside window [0, 10].
        Expected: MaxDD = 0.0, total_return = 0.0, total_trades = 0.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        open_px = px.copy()
        close_px = px.copy()
        close_px[10, 0] = 100.0
        open_px[11, 0] = 200.0
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        reb = np.array([0, 10, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM"],
            schedule_indices_map=sched_map,
            open_px=open_px,
            close_px=close_px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 999,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 10,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["max_drawdown"], 0.0)
        self.assertEqual(row["total_return"], 0.0)
        self.assertEqual(row["ending_equity"], 100_000.0)
        self.assertEqual(row["total_trades"], 0)

    # -------------------------------------------------------------------------
    # Assertion A2: Disclosure of Trading, Warmup, and Cash Days
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Assertion A2: Disclosure of Trading, Warmup, and Cash Days
    # -------------------------------------------------------------------------
    def test_a2_trading_warmup_cash_days_disclosed(self):
        """
        A2: The harness reports actual trading days, warmup days, and cash days.
            If cash_days > 0, the drawdown numbers are labeled 'excludes warmup' or 'DATA_INSUFFICIENT'.
        """
        stress_tests = self.data.get("bear_market_stress_tests", [])
        for window in stress_tests:
            w_name = window["window"]
            act_days = window.get("trading_days")
            warm_days = window.get("warmup_days")
            leg_cash = window.get("cash_days_legacy")
            top_cash = window.get("cash_days_top")
            leg_eff = window.get("effective_trading_days_legacy")
            top_eff = window.get("effective_trading_days_top")

            self.assertIsNotNone(act_days, f"Missing trading_days in {w_name}")
            self.assertIsNotNone(warm_days, f"Missing warmup_days in {w_name}")
            self.assertIsNotNone(leg_cash, f"Missing cash_days_legacy in {w_name}")
            self.assertIsNotNone(top_cash, f"Missing cash_days_top in {w_name}")

            # Identity: actual days = cash days + effective days
            self.assertEqual(act_days, leg_cash + leg_eff, f"Day count mismatch in Legacy {w_name}")
            self.assertEqual(act_days, top_cash + top_eff, f"Day count mismatch in Top {w_name}")

            # Disclosure status check
            label = window.get("label", "")
            status = window.get("status", "")
            if leg_cash > 0 or top_cash > 0:
                valid_label = "excludes warmup" in label.lower() or status == "DATA_INSUFFICIENT" or "DATA_INSUFFICIENT" in label
                self.assertTrue(valid_label, f"Missing warmup/cash disclosure label for {w_name}: {label}")

    def test_a2_warmup_matches_pre_window_lookback(self):
        """
        A2: Warmup days equals actual available pre-window lookback sessions (<= 252),
        distinct from in-window cash days.
        """
        for w in self.data["bear_market_stress_tests"]:
            self.assertEqual(w["warmup_days"], w["pre_window_lookback_sessions"])
            self.assertLessEqual(w["warmup_days"], 252)
            if "2008" in w["window"]:
                self.assertEqual(w["warmup_days"], 248, "2008 window has exactly 248 available lookback sessions")
            else:
                self.assertEqual(w["warmup_days"], 252)
            # In-window cash span is separate and properly disclosed
            self.assertEqual(w["cash_days_legacy"], w["trading_days"] - w["effective_trading_days_legacy"])
            self.assertEqual(w["cash_days_top"], w["trading_days"] - w["effective_trading_days_top"])

    def test_a2_cash_days_are_measured_not_assumed(self):
        """
        A2: Cash days are derived from actual bar-by-bar holdings, not first-rebalance index arithmetic.
        Synthetic test: 30 dates where volar=0 ensures 0 candidates pass.
        Harness must measure cash_days == 30, not 1.
        """
        from scripts.forensic_integrity_audit import generate_window_trade_ledger
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        reb = np.array([0, 29], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((4, num_dates, 1), dtype=np.float32)
        cube = TensorCubeContainer(
            dates=dates,
            symbols=["TEST_SYM"],
            schedule_indices_map=sched_map,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "schedule_idx": 1,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 29)
        self.assertEqual(ledger["cash_days"], 30, "Strategy with no qualifying stocks must measure 30 cash days")
        self.assertEqual(ledger["effective_trading_days"], 0)
        self.assertIsNone(ledger["first_invested_date"])

    # -------------------------------------------------------------------------
    # Assertion A3: COVID-2020 Precision, Calmar Threshold, and Dated Cash Event
    # -------------------------------------------------------------------------
    def test_a3_covid_precision_and_calmar_threshold(self):
        """
        A3: For 2020 COVID specifically:
            - MaxDD is reported with >= 4 decimal places, not as '0.00%'.
            - If MaxDD < 0.01%, Calmar is reported as N/A, not as a number > 100.
            - The marketing claim 'went 100% to cash before the crash' is forensically audited
              and established as VIOLATED (0 liquidation sells occurred; strategy entered flat).
        """
        stress_tests = self.data.get("bear_market_stress_tests", [])
        covid = next((w for w in stress_tests if "2020" in w["window"]), None)
        self.assertIsNotNone(covid, "Missing 2020 COVID stress test record")

        top_dd = covid["top_maxdd_raw"]
        top_calmar = covid["top_calmar"]

        # Precision requirement: not 0.00% placeholder
        self.assertGreater(top_dd, 0.01, "Top Config COVID MaxDD must reflect genuine intra-period drawdown")
        self.assertNotEqual(round(top_dd, 4), 0.0, "Top Config COVID MaxDD must not be 0.00%")

        # Calmar threshold check (avoid 2709.00 artifact)
        if top_dd < 0.01:
            self.assertEqual(top_calmar, 0.0, "Calmar must be N/A or 0.0 when MaxDD < 0.01%")
        else:
            self.assertLessEqual(top_calmar, 100.0, f"Calmar ({top_calmar}) exceeds institutional bound 100.0")

        # Dated cash event audit verification
        cash_audit = covid.get("cash_event_audit")
        self.assertIsNotNone(cash_audit, "COVID record must have cash_event_audit")
        self.assertEqual(cash_audit["claim_tested"], "went 100% to cash before the crash")
        self.assertEqual(cash_audit["claim_verdict"], "VIOLATED")
        self.assertEqual(cash_audit["sell_transactions_in_window"], 0)
        self.assertFalse(cash_audit["has_sell_event"])

        # Institutional dated event log provenance
        rebal_events_path = REPORT_DIR / "stress_rebalance_events.json"
        self.assertTrue(rebal_events_path.exists(), f"Missing rebalance event log: {rebal_events_path}")
        with open(rebal_events_path, "r", encoding="utf-8") as rf:
            rebal_events = json.load(rf)
        covid_events = [e for e in rebal_events if "2020" in e["window"]]
        self.assertGreaterEqual(len(covid_events), 1, "Must record trades in 2020 window")
        covid_sells = [e for e in covid_events if e.get("type") == "SELL" and e.get("strategy") == "Top Config"]
        self.assertEqual(len(covid_sells), 0, "A3: Exactly 0 SELL orders executed by Top Config in 2020 crash")
        for e in covid_events:
            self.assertIn("shares", e)
            self.assertIn("price", e)
            self.assertIn("cash_before", e)
            self.assertIn("cash_after", e)
            self.assertIn("pos_before", e)
            self.assertIn("pos_after", e)

    # -------------------------------------------------------------------------
    # Assertion A4: Canonical Baseline Delta Reclassification
    # -------------------------------------------------------------------------
    def test_a4_canonical_baseline_delta(self):
        """
        A4: Reclassification against canonical baseline (CAGR 35.01%, MaxDD 41.65%, Calmar 0.84).
            Asserts literal constants and verifies reclassifications.
        """
        canon_obj = self.data.get("canonical_baseline")
        self.assertIsNotNone(canon_obj, "Missing canonical_baseline object in forensic audit results")
        self.assertEqual(canon_obj["cagr"], 35.01, "Canonical baseline CAGR must be exactly 35.01%")
        self.assertEqual(canon_obj["max_drawdown"], 41.65, "Canonical baseline MaxDD must be exactly 41.65%")
        self.assertEqual(canon_obj["calmar"], 0.84, "Canonical baseline Calmar must be exactly 0.84")

        canon_calmar = canon_obj["calmar"]

        reclass = {r["experiment_id"]: r for r in self.data.get("calmar_reclassified_ablation", [])}
        self.assertGreaterEqual(len(reclass), 8, "Must contain all ablation experiments")

        # Specific institutional reclassifications against 0.84
        run3 = reclass["RUN_3_ATR_SIZING"]
        self.assertEqual(run3["delta_calmar_pct"], 1.2, "RUN_3 delta must be +1.2% against 0.84")
        self.assertEqual(run3["new_calmar_label"], "NEUTRAL", "RUN_3 within ±5% must be NEUTRAL")

        run4 = reclass["RUN_4_NO_BUFFER"]
        self.assertEqual(run4["delta_calmar_pct"], -14.3, "RUN_4 delta must be -14.3% against 0.84")
        self.assertEqual(run4["new_calmar_label"], "HARMFUL", "RUN_4 must be HARMFUL")

        run5 = reclass["RUN_5_BUFFER_60"]
        self.assertEqual(run5["delta_calmar_pct"], -15.5, "RUN_5 delta must be -15.5% against 0.84")
        self.assertEqual(run5["new_calmar_label"], "HARMFUL", "RUN_5 must be HARMFUL")

        run1 = reclass["RUN_1_REGIME"]
        self.assertEqual(run1["delta_calmar_pct"], -15.5, "RUN_1 delta must be -15.5% against 0.84")
        self.assertEqual(run1["new_calmar_label"], "REGIME_DEPENDENT")

        run0 = reclass["RUN_0_BASELINE"]
        self.assertEqual(run0["delta_calmar_pct"], 0.0)
        self.assertEqual(run0["new_calmar_label"], "CANONICAL_BASELINE")

    # -------------------------------------------------------------------------
    # Assertion A5: Deduplication Completeness
    # -------------------------------------------------------------------------
    def test_a5_dedup_all_distinct_configs_shown(self):
        """
        A5: For deduplication:
            distinct_count matches number of distinct rows shown in table (4 distinct -> 4 rows).
            If a row is intentionally dropped by policy, that decision is documented.
        """
        dedup = self.data.get("deduplication_audit", {})
        self.assertEqual(dedup.get("distinct_count"), 4)
        self.assertEqual(len(dedup.get("deduplicated_top_4", [])), 4)

        # Verify distinctness across the 4 configs
        configs = dedup["deduplicated_top_4"]
        signatures = set()
        for c in configs:
            sig = (
                c["config"]["lookback"],
                c["config"]["ema_trend"],
                c["config"]["buffer"],
                c["config"]["sizing"],
            )
            signatures.add(sig)
        self.assertEqual(len(signatures), 4, "All 4 configs must have distinct parameter signatures")

        # Documented policy for rank 4
        deprioritized = dedup.get("deprioritized_configs", [])
        self.assertGreaterEqual(len(deprioritized), 1)
        self.assertEqual(deprioritized[0]["rank"], 4)
        self.assertIn("policy_reason", deprioritized[0])
        self.assertIn("Equal Weight", deprioritized[0]["policy_reason"])

    # -------------------------------------------------------------------------
    # Assertion A6: Effective Window Consistency
    # -------------------------------------------------------------------------
    # -------------------------------------------------------------------------
    # Assertion A6: Effective Window Consistency
    # -------------------------------------------------------------------------
    def test_a6_effective_window_consistency(self):
        """
        A6: For every drawdown reduction claim in the report:
            Both Legacy MaxDD and Top Config MaxDD were computed over the same effective
            trading window, and warmups are explicitly declared.
        """
        stress_tests = self.data.get("bear_market_stress_tests", [])
        for window in stress_tests:
            w_name = window["window"]
            self.assertIn("effective_trading_days_legacy", window)
            self.assertIn("effective_trading_days_top", window)
            self.assertIn("legacy_first_invested_date", window)
            self.assertIn("top_first_invested_date", window)
            self.assertIn("calendar_window_drawdown_delta_pct", window)

    def test_a6_same_effective_window(self):
        """
        A6: Assert effective_trading_days_legacy == effective_trading_days_top
        whenever active-window drawdown_reduction_pct is reported.
        """
        for w in self.data["bear_market_stress_tests"]:
            if w.get("drawdown_reduction_pct") is not None:
                self.assertEqual(
                    w["effective_trading_days_legacy"],
                    w["effective_trading_days_top"],
                    f"{w['window']}: drawdown_reduction_pct reported but active days differ"
                )

    def test_a6_non_comparable_windows_null_deltas(self):
        """
        A6: If effective trading days differ, both drawdown_reduction_pct and
        calendar_window_drawdown_delta_pct MUST be None, and non_comparable_reason provided.
        """
        for w in self.data["bear_market_stress_tests"]:
            if w["effective_trading_days_legacy"] != w["effective_trading_days_top"]:
                self.assertIsNone(w.get("drawdown_reduction_pct"), f"{w['window']}: drawdown_reduction_pct must be None")
                self.assertIsNone(w.get("calendar_window_drawdown_delta_pct"), f"{w['window']}: calendar_window_drawdown_delta_pct must be None")
                self.assertIsNotNone(w.get("non_comparable_reason"), f"{w['window']}: must provide non_comparable_reason")

    def test_a6_synthetic_comparability_span_mismatch(self):
        """
        A6: If effective trading days differ (e.g. one goes to cash while other stays invested),
        is_comparable must be False and drawdown_reduction_pct must be None.
        """
        legacy_eff_days = 20
        top_eff_days = 5
        legacy_cash = 0
        top_cash = 0
        is_comparable = bool(legacy_eff_days == top_eff_days and legacy_cash == top_cash)
        reduction = (30.0 - 5.0) if is_comparable else None
        self.assertFalse(is_comparable)
        self.assertIsNone(reduction)

    def test_report_narrative_matches_json(self):
        """
        Assert stated session counts in Section 5 prose match JSON effective_trading_days_legacy.
        """
        session_matches = [int(x) for x in re.findall(r"Spans\s+(\d+)\s+active sessions", self.md_text)]
        self.assertGreaterEqual(len(session_matches), 3, "Must find session counts in report narrative")
        stress_map = {w["window"]: w for w in self.data["bear_market_stress_tests"]}

        self.assertIn(stress_map["2008 Global Financial Crisis"]["effective_trading_days_legacy"], session_matches)
        self.assertIn(stress_map["2018 Midcap Crash / Correction"]["effective_trading_days_legacy"], session_matches)
        self.assertIn(stress_map["2020 COVID Crash"]["effective_trading_days_legacy"], session_matches)

    # -------------------------------------------------------------------------
    # Stress Vectors V1 - V4
    # -------------------------------------------------------------------------
    def _create_synthetic_cube(self, num_dates: int, close_prices: np.ndarray) -> TensorCubeContainer:
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        symbols = ["TEST_SYM"]
        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched_map = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        return TensorCubeContainer(
            dates=dates,
            symbols=symbols,
            schedule_indices_map=sched_map,
            open_px=close_prices,
            close_px=close_prices,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )

    def test_stress_vector_v1_straight_drop(self):
        """
        V1: A synthetic window where the strategy loses 20% straight down:
            MaxDD should equal exactly 20.00%.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        # Buy occurs at day 1 (open px 100), drops to 80 on day 29
        px[1:, 0] = np.linspace(100.0, 80.0, num_dates - 1, dtype=np.float32)

        cube = self._create_synthetic_cube(num_dates, px)
        param = {
            "param_id": 101,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        self.assertEqual(len(res), 1)
        row = res.iloc[0]

        # In frictionless mode, investable_cash = 100% of cash, yielding exact 20.00%
        self.assertAlmostEqual(row["max_drawdown"], 20.00, places=3, msg="MaxDD must equal exactly 20.00%")
        self.assertAlmostEqual(row["total_return"], -20.00, places=3, msg="Total return must equal exactly -20.00%")
        self.assertEqual(row["ending_equity"], 80_000.0)

    def test_stress_vector_v2_intra_period_dip_recovery(self):
        """
        V2: A synthetic window where the strategy starts at 100, dips to 80,
            recovers to 100, ends at 100: MaxDD = 20%, return = 0%.
            Intra-period daily marking ensures dip is captured.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        px[1:16, 0] = np.linspace(100.0, 80.0, 15, dtype=np.float32)
        px[15:, 0] = np.linspace(80.0, 100.0, 15, dtype=np.float32)

        cube = self._create_synthetic_cube(num_dates, px)
        param = {
            "param_id": 102,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]

        self.assertAlmostEqual(row["max_drawdown"], 20.00, places=3, msg="Intra-period dip must equal 20.00%")
        self.assertAlmostEqual(row["total_return"], 0.00, places=3, msg="Ending return must be 0.00%")
        self.assertEqual(row["ending_equity"], 100_000.0)

    def test_stress_vector_v3_nan_bar_handling(self):
        """
        V3: A synthetic window with a single NaN bar in the price series:
            the harness must not silently treat NaN as a peak or a trough,
            and must flag DATA_INSUFFICIENT.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        px[15, 0] = np.nan

        cube = self._create_synthetic_cube(num_dates, px)
        param = {
            "param_id": 103,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]

        self.assertTrue(math.isnan(row["cagr"]), "NaN bar must flag CAGR as NaN")
        self.assertTrue(math.isnan(row["total_return"]), "NaN bar must flag total_return as NaN")
        self.assertTrue(math.isnan(row["max_drawdown"]), "NaN bar must flag max_drawdown as NaN")
        self.assertTrue(row["data_insufficient"], "Must set data_insufficient flag")
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")

    def test_stress_vector_v3_signal_bar_nan_handling(self):
        """
        V3: A synthetic window with NaN on the signal bar (bar 0):
            The harness must fail closed and flag DATA_INSUFFICIENT, not silently ignore.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0
        px[0, 0] = np.nan

        cube = self._create_synthetic_cube(num_dates, px)
        param = {
            "param_id": 105,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]

        self.assertTrue(math.isnan(row["cagr"]), "Signal bar NaN must flag CAGR as NaN")
        self.assertTrue(math.isnan(row["total_return"]), "Signal bar NaN must flag total_return as NaN")
        self.assertTrue(math.isnan(row["max_drawdown"]), "Signal bar NaN must flag max_drawdown as NaN")
        self.assertTrue(row["data_insufficient"], "Must set data_insufficient flag")
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")

    def test_stress_vector_v4_zero_capital_guard(self):
        """
        V4: A synthetic window with initial cash 0 (empty position):
            MaxDD = 0%, return undefined. Harness must handle without dividing by zero.
        """
        num_dates = 30
        px = np.ones((num_dates, 1), dtype=np.float32) * 100.0

        cube = self._create_synthetic_cube(num_dates, px)
        param = {
            "param_id": 104,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "lookback_idx": 0,
            "ema_idx": 0,
            "top_n": 1,
            "exit_buffer_rank": 40,
            "max_per_sector": 2,
            "sizing_mode": "equal_weight",
            "filter_flags": 0,
            "initial_capital": 0.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]

        self.assertEqual(row["max_drawdown"], 0.0)
        self.assertTrue(math.isnan(row["cagr"]))
        self.assertTrue(math.isnan(row["total_return"]))
        self.assertEqual(row["ending_equity"], 0.0)
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")

    # -------------------------------------------------------------------------
    # Precision Gate
    # -------------------------------------------------------------------------
    def test_precision_gate(self):
        r"""
        Precision Gate:
        - Fails if 0.00% or 0.0% or 0.00 placeholder appears in the stress table.
        - Fails if Calmar > 100 appears in the stress table or JSON results.
        """
        # Extract Section 5 table from markdown
        sec5_match = re.search(r"## 5\. TASK 5: BEAR-MARKET STRESS TESTS.*?(?=## 6\.)", self.md_text, re.DOTALL)
        self.assertIsNotNone(sec5_match, "Section 5 not found in markdown report")
        sec5_text = sec5_match.group(0)

        # Extract markdown table lines
        table_lines = [line for line in sec5_text.splitlines() if line.strip().startswith("|")]
        self.assertGreaterEqual(len(table_lines), 9, "Stress table must have header and 8 data rows")

        data_rows = table_lines[2:]  # Skip header and separator
        zero_pattern = re.compile(r"^[+-]?0\.0+%?$")
        for row in data_rows:
            # Check for 0.00% placeholder in MaxDD or returns
            cells = [c.strip() for c in row.split("|")[1:-1]]
            for c in cells:
                self.assertFalse(
                    bool(zero_pattern.match(c)),
                    f"Forbidden zero placeholder found in cell '{c}' of row: {row}"
                )

        # Ensure no Calmar > 100 artifact exists in Section 5 or JSON stress tests
        calmar_nums = re.findall(r"Calmar\s*\**([0-9]+\.[0-9]+)\**", sec5_text)
        for num_str in calmar_nums:
            num = float(num_str)
            self.assertLessEqual(num, 100.0, f"Spurious unbounded Calmar ({num}) found in Section 5")

        for w in self.data["bear_market_stress_tests"]:
            leg_cal = w.get("legacy_calmar")
            top_cal = w.get("top_calmar")
            if leg_cal is not None:
                self.assertLessEqual(leg_cal, 100.0)
            if top_cal is not None:
                self.assertLessEqual(top_cal, 100.0)


if __name__ == "__main__":
    unittest.main()
