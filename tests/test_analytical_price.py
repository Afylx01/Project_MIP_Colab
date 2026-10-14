"""
MIP Android — Corporate-Action Analytical Price Engine Tests
Directive: STAGE-4-5-CORPORATE-ACTION-TEST-01
"""

import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from core.analytical_price import (
    AnalyticalPriceEngine,
    CorporateActionEvent,
    ActionNature,
    ActionType,
)
from core.data_engine import (
    get_base_dir,
    load_bars,
)
from core.identity import SecurityIdentityManager


class TestAnalyticalPriceEngine(unittest.TestCase):
    """Verifies corporate action handling, partitioning, continuous adjustment, and PIT safety."""

    def setUp(self):
        self.base_dir = get_base_dir()
        self.reg_path = self.base_dir / "data" / "corporate_actions_registry.json"
        self.engine = AnalyticalPriceEngine(self.reg_path)

    def test_seven_event_forensic_regression(self):
        """Verifies the 7 corporate-action events established in Phase 7/Phase 9."""
        # 1. Demerger events: TMPV, VEDL, INDIAGLYCO, SKFINDIA, TRIVENI
        demergers = ["TMPV", "VEDL", "INDIAGLYCO", "SKFINDIA", "TRIVENI"]
        for sym in demergers:
            raw_df = load_bars(start_date="2024-01-01", end_date="2026-10-01", symbols=[sym])
            adj_df, diag = self.engine.derive_analytical_series(sym, raw_df, as_of_date="2026-10-01")
            self.assertEqual(diag.get("treatment"), "BOUNDARY_HISTORY_PARTITIONING", f"{sym} should be partitioned")
            self.assertTrue(diag.get("is_partitioned"), f"{sym} is_partitioned should be True")
            self.assertFalse(diag.get("is_blocked_unresolved"), f"{sym} should not be blocked")

        # 2. Continuous backward adjustment: PGIL (1:1 Bonus on 2026-09-11, factor 0.5)
        pgil_raw = load_bars(start_date="2024-01-01", end_date="2026-10-01", symbols=["PGIL"])
        pgil_adj, pgil_diag = self.engine.derive_analytical_series("PGIL", pgil_raw, as_of_date="2026-10-01")
        self.assertEqual(pgil_diag.get("treatment"), "CONTINUOUS_BACKWARD_ADJUSTMENT")
        self.assertEqual(pgil_diag.get("actions_applied"), 1)
        pre_bonus = pgil_adj[pgil_adj["date"] < "2026-09-11"]
        raw_pre_bonus = pgil_raw[pgil_raw["date"] < "2026-09-11"]
        ratio = (pre_bonus["close"].iloc[-1] / raw_pre_bonus["close"].iloc[-1])
        self.assertAlmostEqual(ratio, 0.5, places=4, msg="PGIL bonus factor ratio mismatch")

        # 3. Genuine market crash: POLICYBZR (-36% drop, unquarantined)
        pbzr_raw = load_bars(start_date="2024-01-01", end_date="2026-10-01", symbols=["POLICYBZR"])
        pbzr_adj, pbzr_diag = self.engine.derive_analytical_series("POLICYBZR", pbzr_raw, as_of_date="2026-10-01")
        self.assertEqual(pbzr_diag.get("treatment"), "RAW_CONTINUOUS")
        self.assertEqual(len(pbzr_adj), len(pbzr_raw))

    def test_point_in_time_isolation(self):
        """Verifies future corporate actions are completely invisible before effective date."""
        pgil_raw = load_bars(start_date="2025-01-01", end_date="2026-10-01", symbols=["PGIL"])

        # As of 2026-01-01: bonus is in the future
        adj_hist, diag_hist = self.engine.derive_analytical_series("PGIL", pgil_raw, as_of_date="2026-01-01")
        self.assertEqual(diag_hist["actions_applied"], 0)
        self.assertEqual(diag_hist["treatment"], "RAW_CONTINUOUS")
        raw_hist = pgil_raw[pgil_raw["date"] <= "2026-01-01"]
        self.assertTrue(np.allclose(adj_hist["close"], raw_hist["close"]))

        # As of 2026-10-01: bonus is effective
        adj_prod, diag_prod = self.engine.derive_analytical_series("PGIL", pgil_raw, as_of_date="2026-10-01")
        self.assertEqual(diag_prod["actions_applied"], 1)
        self.assertEqual(diag_prod["treatment"], "CONTINUOUS_BACKWARD_ADJUSTMENT")

    def test_synthetic_12_scenarios(self):
        """Tests 12 synthetic corporate action scenarios."""
        dates = pd.date_range("2025-01-01", periods=300, freq="B").strftime("%Y-%m-%d").tolist()

        # 1. SPLIT 2:1
        df_s1 = pd.DataFrame({"date": dates, "open": [100.0]*200 + [50.0]*100, "high": [105.0]*200 + [52.5]*100,
                              "low": [95.0]*200 + [47.5]*100, "close": [100.0]*200 + [50.0]*100, "volume": [1000.0]*300})
        act_s1 = CorporateActionEvent(
            symbol="SYNTH_SPLIT", security_id="SEC_S1", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.SPLIT, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.5,
            resulting_entities=["SYNTH_SPLIT"], source_authority="TEST", source_reference="T1", ingestion_timestamp=dates[200]
        )
        eng_s1 = AnalyticalPriceEngine()
        eng_s1.actions_by_symbol = {"SYNTH_SPLIT": [act_s1]}
        adj_s1, d_s1 = eng_s1.derive_analytical_series("SYNTH_SPLIT", df_s1, as_of_date=dates[-1])
        self.assertAlmostEqual(adj_s1["close"].iloc[199], 50.0, places=4)
        self.assertFalse(d_s1["is_blocked_unresolved"])

        # 2. BONUS 1:1
        act_s2 = CorporateActionEvent(
            symbol="SYNTH_BONUS", security_id="SEC_S2", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.BONUS, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.5,
            resulting_entities=["SYNTH_BONUS"], source_authority="TEST", source_reference="T2", ingestion_timestamp=dates[200]
        )
        eng_s2 = AnalyticalPriceEngine()
        eng_s2.actions_by_symbol = {"SYNTH_BONUS": [act_s2]}
        adj_s2, d_s2 = eng_s2.derive_analytical_series("SYNTH_BONUS", df_s1.copy(), as_of_date=dates[-1])
        self.assertAlmostEqual(adj_s2["close"].iloc[199], 50.0, places=4)

        # 3. CONSOLIDATION (Reverse split 1:5)
        df_s3 = pd.DataFrame({"date": dates, "open": [10.0]*200 + [50.0]*100, "high": [11.0]*200 + [55.0]*100,
                              "low": [9.0]*200 + [45.0]*100, "close": [10.0]*200 + [50.0]*100, "volume": [5000.0]*300})
        act_s3 = CorporateActionEvent(
            symbol="SYNTH_CONS", security_id="SEC_S3", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.CONSOLIDATION, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=5.0,
            resulting_entities=["SYNTH_CONS"], source_authority="TEST", source_reference="T3", ingestion_timestamp=dates[200]
        )
        eng_s3 = AnalyticalPriceEngine()
        eng_s3.actions_by_symbol = {"SYNTH_CONS": [act_s3]}
        adj_s3, d_s3 = eng_s3.derive_analytical_series("SYNTH_CONS", df_s3, as_of_date=dates[-1])
        self.assertAlmostEqual(adj_s3["close"].iloc[199], 50.0, places=4)

        # 4. DEMERGER
        df_s4 = pd.DataFrame({"date": dates, "open": [100.0]*200 + [40.0]*100, "high": [105.0]*200 + [42.0]*100,
                              "low": [95.0]*200 + [38.0]*100, "close": [100.0]*200 + [40.0]*100, "volume": [1000.0]*300})
        act_s4 = CorporateActionEvent(
            symbol="SYNTH_DEMERGER", security_id="SEC_S4", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.DEMERGER, action_nature=ActionNature.ENTERPRISE_ALTERING, factor=0.4,
            resulting_entities=["SYNTH_DEMERGER", "SYNTH_SPIN"], source_authority="TEST", source_reference="T4", ingestion_timestamp=dates[200]
        )
        eng_s4 = AnalyticalPriceEngine()
        eng_s4.actions_by_symbol = {"SYNTH_DEMERGER": [act_s4]}
        adj_s4, d_s4 = eng_s4.derive_analytical_series("SYNTH_DEMERGER", df_s4, as_of_date=dates[-1])
        self.assertEqual(len(adj_s4), 100)
        self.assertTrue(d_s4["is_partitioned"])

        # 5. SPIN-OFF
        act_s5 = CorporateActionEvent(
            symbol="SYNTH_SPIN", security_id="SEC_S5", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.SPIN_OFF, action_nature=ActionNature.ENTERPRISE_ALTERING, factor=0.5,
            resulting_entities=["SYNTH_SPIN"], source_authority="TEST", source_reference="T5", ingestion_timestamp=dates[200]
        )
        eng_s5 = AnalyticalPriceEngine()
        eng_s5.actions_by_symbol = {"SYNTH_SPIN": [act_s5]}
        adj_s5, d_s5 = eng_s5.derive_analytical_series("SYNTH_SPIN", df_s4.copy(), as_of_date=dates[-1])
        self.assertEqual(len(adj_s5), 100)

        # 6. MERGER
        act_s6 = CorporateActionEvent(
            symbol="SYNTH_MERGER", security_id="SEC_S6", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.MERGER, action_nature=ActionNature.ENTERPRISE_ALTERING, factor=1.0,
            resulting_entities=["SYNTH_MERGER"], source_authority="TEST", source_reference="T6", ingestion_timestamp=dates[200]
        )
        eng_s6 = AnalyticalPriceEngine()
        eng_s6.actions_by_symbol = {"SYNTH_MERGER": [act_s6]}
        adj_s6, d_s6 = eng_s6.derive_analytical_series("SYNTH_MERGER", df_s4.copy(), as_of_date=dates[-1])
        self.assertEqual(len(adj_s6), 100)

        # 7. TICKER CHANGE
        id_mgr = SecurityIdentityManager()
        id_mgr.register_ticker_change("SEC_TEST_TICKER", "OLDTICKER", "NEWTICKER", dates[150])
        sec_old = id_mgr.resolve_security_id("OLDTICKER", dates[100])
        sec_new = id_mgr.resolve_security_id("NEWTICKER", dates[200])
        self.assertEqual(sec_old, sec_new)

        # 8. GENUINE CRASH (-35% drop preserved)
        df_s8 = pd.DataFrame({"date": dates, "open": [100.0]*200 + [65.0]*100, "high": [102.0]*200 + [66.0]*100,
                              "low": [98.0]*200 + [64.0]*100, "close": [100.0]*200 + [65.0]*100, "volume": [1000.0]*300})
        eng_s8 = AnalyticalPriceEngine()
        adj_s8, d_s8 = eng_s8.derive_analytical_series("SYNTH_CRASH", df_s8, as_of_date=dates[-1])
        self.assertFalse(d_s8["is_blocked_unresolved"])
        self.assertEqual(d_s8["treatment"], "RAW_CONTINUOUS")

        # 9. CORRUPT / UNEXPLAINED DROP (>40% drop fails closed)
        df_s9 = pd.DataFrame({"date": dates, "open": [100.0]*200 + [40.0]*100, "high": [102.0]*200 + [42.0]*100,
                              "low": [98.0]*200 + [38.0]*100, "close": [100.0]*200 + [40.0]*100, "volume": [1000.0]*300})
        eng_s9 = AnalyticalPriceEngine()
        adj_s9, d_s9 = eng_s9.derive_analytical_series("SYNTH_CORRUPT", df_s9, as_of_date=dates[-1])
        self.assertTrue(d_s9["is_blocked_unresolved"])
        self.assertEqual(d_s9["treatment"], "UNRESOLVED_CRASH")

        # 10. DELAYED / FUTURE ACTION
        act_s10 = CorporateActionEvent(
            symbol="SYNTH_FUTURE", security_id="SEC_S10", ex_date=dates[250], record_date=dates[250], effective_date=dates[250],
            action_type=ActionType.BONUS, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.5,
            resulting_entities=["SYNTH_FUTURE"], source_authority="TEST", source_reference="T10", ingestion_timestamp=dates[250]
        )
        eng_s10 = AnalyticalPriceEngine()
        eng_s10.actions_by_symbol = {"SYNTH_FUTURE": [act_s10]}
        adj_s10, d_s10 = eng_s10.derive_analytical_series("SYNTH_FUTURE", df_s1.copy(), as_of_date=dates[150])
        self.assertEqual(d_s10["actions_applied"], 0)
        self.assertEqual(d_s10["treatment"], "RAW_CONTINUOUS")

        # 11. RESIDUAL DISLOCATION AFTER FACTOR
        act_s11 = CorporateActionEvent(
            symbol="SYNTH_INCOMPLETE", security_id="SEC_S11", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.BONUS, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.9,
            resulting_entities=["SYNTH_INCOMPLETE"], source_authority="TEST", source_reference="T11", ingestion_timestamp=dates[200]
        )
        eng_s11 = AnalyticalPriceEngine()
        eng_s11.actions_by_symbol = {"SYNTH_INCOMPLETE": [act_s11]}
        adj_s11, d_s11 = eng_s11.derive_analytical_series("SYNTH_INCOMPLETE", df_s9.copy(), as_of_date=dates[-1])
        self.assertTrue(d_s11["is_blocked_unresolved"])

        # 12. COMPOUND MULTI-STAGE CORPORATE ACTIONS (Split 2:1 then Bonus 1:1)
        act_s12a = CorporateActionEvent(
            symbol="SYNTH_COMPOUND", security_id="SEC_S12", ex_date=dates[100], record_date=dates[100], effective_date=dates[100],
            action_type=ActionType.SPLIT, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.5,
            resulting_entities=["SYNTH_COMPOUND"], source_authority="TEST", source_reference="T12a", ingestion_timestamp=dates[100]
        )
        act_s12b = CorporateActionEvent(
            symbol="SYNTH_COMPOUND", security_id="SEC_S12", ex_date=dates[200], record_date=dates[200], effective_date=dates[200],
            action_type=ActionType.BONUS, action_nature=ActionNature.ENTERPRISE_PRESERVING, factor=0.5,
            resulting_entities=["SYNTH_COMPOUND"], source_authority="TEST", source_reference="T12b", ingestion_timestamp=dates[200]
        )
        df_s12 = pd.DataFrame({"date": dates, "open": [200.0]*100 + [100.0]*100 + [50.0]*100,
                               "high": [205.0]*100 + [102.5]*100 + [51.2]*100,
                               "low": [195.0]*100 + [97.5]*100 + [48.8]*100,
                               "close": [200.0]*100 + [100.0]*100 + [50.0]*100, "volume": [1000.0]*300})
        eng_s12 = AnalyticalPriceEngine()
        eng_s12.actions_by_symbol = {"SYNTH_COMPOUND": [act_s12a, act_s12b]}
        adj_s12, d_s12 = eng_s12.derive_analytical_series("SYNTH_COMPOUND", df_s12, as_of_date=dates[-1])
        self.assertAlmostEqual(adj_s12["close"].iloc[50], 50.0, places=4)
        self.assertAlmostEqual(adj_s12["close"].iloc[150], 50.0, places=4)
        self.assertFalse(d_s12["is_blocked_unresolved"])
        self.assertEqual(d_s12["actions_applied"], 2)


if __name__ == "__main__":
    unittest.main()
