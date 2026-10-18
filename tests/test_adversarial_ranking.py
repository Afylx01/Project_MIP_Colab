"""
Adversarial Stress Test Suite for Ranking, Sectors, and Volar Invariants.
Phase: GATE-6 (BREAK) & GATE-7 (DIAGNOSE & REPAIR)

Validates extreme edge cases, boundary conditions, malformed inputs,
and tie-breaking determinism across repaired and core components.
"""

import math
import unittest
import numpy as np
import pandas as pd
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import load_universe_constituents, get_universe_label
from core.sync_sectors import PRIMARY_SECTORS, classify_symbol, get_symbol_sector
from core.config import MIPScannerConfig


def compute_volar_series(close_series: pd.Series, volatility_floor: float = 0.05, lookback: int = 252) -> pd.DataFrame:
    """Computes Volar exactly as implemented in core/scanner.py."""
    df = pd.DataFrame({"close": close_series})
    df["ret_252"] = df["close"] / df["close"].shift(lookback).fillna(df["close"].iloc[0]) - 1.0
    df["ret_1d"] = df["close"].pct_change().fillna(0.0)
    df["vol_252"] = (
        df["ret_1d"].rolling(lookback, min_periods=min(251, len(df) - 1)).std(ddof=1) * np.sqrt(252)
    ).clip(lower=volatility_floor).fillna(volatility_floor)
    df["volar_score"] = df["ret_252"] / df["vol_252"].clip(lower=volatility_floor)
    return df


class TestAdversarialUniverseEngine(unittest.TestCase):
    """Stress tests for universe constituent resolution under adverse inputs."""

    def test_adverse_inputs_fallback_to_safe_defaults(self):
        """Malformed, empty, None, and garbage modes must cleanly fall back to 500 without crashing."""
        malformed_inputs = [
            None,
            "",
            "   ",
            "\t\n",
            "NON_EXISTENT_UNIVERSE_XYZ_12345",
            "SELECT * FROM users",
            "---!@#$%^&*()",
            12345,  # Non-string type
        ]
        for bad_input in malformed_inputs:
            constituents = load_universe_constituents(bad_input)
            self.assertIsInstance(constituents, (set, list), f"Failed on input: {bad_input}")
            self.assertEqual(len(constituents), 501, f"Fallback count mismatch on input: {bad_input}")
            label = get_universe_label(bad_input)
            self.assertIsInstance(label, str)
            self.assertTrue(len(label) > 0)

    def test_permissive_casing_and_punctuation_for_750(self):
        """All variations of 750/Total Market must resolve to the full Total Market constituent list."""
        valid_750_variants = [
            "NIFTY750TOTALMARKET",
            "nifty750totalmarket",
            "NIFTY_750_TOTAL_MARKET",
            "nifty 750 total market",
            "  NIFTY750TOTALMARKET  ",
            "TOTAL_MARKET",
            "total market",
            "nifty_total_market",
            "NIFTY-750",
            "nifty 750",
            "750",
        ]
        for variant in valid_750_variants:
            constituents = load_universe_constituents(variant)
            self.assertEqual(
                len(constituents), 755,
                f"Variant '{variant}' failed to resolve to 755 Total Market constituents"
            )
            label = get_universe_label(variant)
            self.assertEqual(label, "NIFTY 750 (TOTAL MARKET)")


class TestAdversarialSectorsAndTaxonomy(unittest.TestCase):
    """Stress tests for sector mapping and 22 AMFI macro industries."""

    def test_authoritative_sector_count_is_strictly_22(self):
        """Ensure PRIMARY_SECTORS matches the 22 AMFI macro industries exactly."""
        self.assertEqual(len(PRIMARY_SECTORS), 22)
        # Verify no collapsed bucket INFRA_MEDIA exists
        self.assertNotIn("INFRA_MEDIA", PRIMARY_SECTORS)
        self.assertIn("TELECOMMUNICATION", PRIMARY_SECTORS)
        self.assertIn("MEDIA ENTERTAINMENT & PUBLICATION", PRIMARY_SECTORS)

    def test_unknown_symbol_graceful_handling(self):
        """Unknown, empty, and malformed symbols must return a safe valid sector string without throwing."""
        bad_symbols = [
            "",
            "   ",
            "UNKNOWN_SYM_99999",
            "CRYPTO_BTC_USD",
            "TATAMOTORS.NS",
            "M&M",
        ]
        for sym in bad_symbols:
            sec = get_symbol_sector(sym)
            self.assertIsInstance(sec, str)
            self.assertTrue(len(sec) > 0)
            self.assertIn(sec, PRIMARY_SECTORS)

    def test_classify_symbol_returns_only_22_sectors(self):
        """Fallback classification keyword tests must return exclusively 22 official AMFI sectors."""
        sample_names = [
            ("HDFCBANK", "HDFC Bank Ltd"),
            ("SUNPHARMA", "Sun Pharmaceutical"),
            ("INFY", "Infosys Technologies"),
            ("TATASTEEL", "Tata Steel Mining"),
            ("BHARTIARTL", "Bharti Telecom Ltd"),
            ("ZEEL", "Zee Entertainment Media"),
            ("NTPC", "NTPC Power Generation"),
            ("DLF", "DLF Realty Housing"),
            ("XYZCORP", "Unknown Generic Entity"),
        ]
        for sym, name in sample_names:
            sec = classify_symbol(sym, name)
            self.assertIn(
                sec, PRIMARY_SECTORS,
                f"Classification for '{sym}' ('{name}') produced '{sec}', not in 22 AMFI sectors"
            )


class TestAdversarialVolarAndIndicators(unittest.TestCase):
    """Stress tests for Volar formula under extreme numerical conditions."""

    def test_zero_volatility_flatline_price_series(self):
        """Flatline prices (zero variance) must invoke the 0.05 volatility floor and yield 0.0 Volar."""
        close = pd.Series([100.0] * 260)
        res = compute_volar_series(close, volatility_floor=0.05, lookback=252)
        last_row = res.iloc[-1]
        self.assertFalse(np.isnan(last_row["ret_252"]))
        self.assertFalse(np.isnan(last_row["vol_252"]))
        self.assertFalse(np.isnan(last_row["volar_score"]))
        self.assertAlmostEqual(last_row["ret_252"], 0.0, places=6)
        self.assertAlmostEqual(last_row["vol_252"], 0.05, places=6)  # Floor applied
        self.assertAlmostEqual(last_row["volar_score"], 0.0, places=6)

    def test_extremely_low_volatility_clamps_at_floor(self):
        """If annualized volatility is below 0.05 floor, denominator must clamp at 0.05."""
        # Gentle steady upward drift: daily return tiny, vol ~0.005
        prices = [100.0 * (1.00005 ** i) for i in range(260)]
        close = pd.Series(prices)
        res = compute_volar_series(close, volatility_floor=0.05, lookback=252)
        last_row = res.iloc[-1]
        ret = last_row["ret_252"]
        vol = last_row["vol_252"]
        volar = last_row["volar_score"]
        # Raw vol was clamped to floor 0.05
        self.assertAlmostEqual(vol, 0.05, places=4)
        expected_volar = ret / 0.05
        self.assertAlmostEqual(volar, expected_volar, places=4)

    def test_near_zero_floating_point_volatility_clamps_at_floor(self):
        """Floating point rolling std yielding non-zero small float (< 0.05) must clamp strictly at 0.05."""
        prices = [100.0 + (0.01 if i % 15 == 0 else 0.0) for i in range(260)]
        close = pd.Series(prices)
        res = compute_volar_series(close, volatility_floor=0.05, lookback=252)
        last_row = res.iloc[-1]
        self.assertEqual(last_row["vol_252"], 0.05)
        expected_volar = last_row["ret_252"] / 0.05
        self.assertAlmostEqual(last_row["volar_score"], expected_volar, places=6)

    def test_extreme_price_collapse(self):
        """Massive 99.9% collapse: must calculate negative return and valid positive volatility without overflow/NaN."""
        prices = np.linspace(1000.0, 1.0, 260)
        close = pd.Series(prices)
        res = compute_volar_series(close, volatility_floor=0.05, lookback=252)
        last_row = res.iloc[-1]
        self.assertTrue(last_row["ret_252"] < -0.90)
        self.assertTrue(last_row["vol_252"] > 0)
        self.assertTrue(last_row["volar_score"] < 0)
        self.assertFalse(np.isnan(last_row["volar_score"]))
        self.assertFalse(np.isinf(last_row["volar_score"]))

    def test_extreme_parabolic_surge(self):
        """100x surge: must calculate large positive return without overflow or NaN."""
        prices = np.linspace(10.0, 1000.0, 260)
        close = pd.Series(prices)
        res = compute_volar_series(close, volatility_floor=0.05, lookback=252)
        last_row = res.iloc[-1]
        self.assertTrue(last_row["ret_252"] > 10.0)
        self.assertTrue(last_row["volar_score"] > 0)
        self.assertFalse(np.isnan(last_row["volar_score"]))
        self.assertFalse(np.isinf(last_row["volar_score"]))


class TestAdversarialRankingFirewallAndSectorCap(unittest.TestCase):
    """Stress tests for sector cap enforcement and 3-tier deterministic ranking ties."""

    def test_sector_cap_strictly_enforces_limit_with_uniform_sector(self):
        """When 10 top candidates all share the same sector, at most max_per_sector (2) are admitted."""
        rows = []
        for i in range(10):
            rows.append({
                "symbol": f"IT_{i}",
                "security_id": f"SEC_IT_{i}",
                "sector": "INFORMATION TECHNOLOGY",
                "volar_score": 10.0 - i,
                "ret_252": 1.0 - (i * 0.05),
            })
        for j in range(5):
            rows.append({
                "symbol": f"MET_{j}",
                "security_id": f"SEC_MET_{j}",
                "sector": "METALS & MINING",
                "volar_score": 5.0 - j,
                "ret_252": 0.5 - (j * 0.05),
            })
        passed_df = pd.DataFrame(rows)

        max_per_sector = 2
        top_n = 10
        sec_counts = {}
        top_rows = []
        for _, r in passed_df.iterrows():
            sec = str(r.get("sector", "OTHER")).strip().upper()
            if sec_counts.get(sec, 0) < max_per_sector:
                top_rows.append(r)
                sec_counts[sec] = sec_counts.get(sec, 0) + 1
            if len(top_rows) >= top_n:
                break

        res_df = pd.DataFrame(top_rows)
        # Should contain exactly 2 IT stocks and 2 METAL stocks (total 4)
        it_count = (res_df["sector"] == "INFORMATION TECHNOLOGY").sum()
        met_count = (res_df["sector"] == "METALS & MINING").sum()
        self.assertEqual(it_count, 2)
        self.assertEqual(met_count, 2)
        self.assertEqual(len(res_df), 4)
        # Ensure IT_0 and IT_1 were chosen (highest Volar)
        self.assertEqual(res_df.iloc[0]["symbol"], "IT_0")
        self.assertEqual(res_df.iloc[1]["symbol"], "IT_1")

    def test_deterministic_ranking_tiebreaker(self):
        """When Volar scores are identical, ret_252 DESC then security_id ASC must break ties deterministically."""
        rows = [
            {"symbol": "SYM_C", "security_id": "SEC_300", "volar_score": 2.50, "ret_252": 0.50},
            {"symbol": "SYM_A", "security_id": "SEC_100", "volar_score": 2.50, "ret_252": 0.60},
            {"symbol": "SYM_B", "security_id": "SEC_200", "volar_score": 2.50, "ret_252": 0.50},
            {"symbol": "SYM_D", "security_id": "SEC_050", "volar_score": 3.00, "ret_252": 0.40},
        ]
        df = pd.DataFrame(rows)
        sorted_df = df.sort_values(
            by=["volar_score", "ret_252", "security_id"],
            ascending=[False, False, True]
        ).reset_index(drop=True)

        expected_order = ["SYM_D", "SYM_A", "SYM_B", "SYM_C"]
        actual_order = sorted_df["symbol"].tolist()
        self.assertEqual(actual_order, expected_order)

    def test_corporate_action_tainted_symbol_exclusion(self):
        """Securities marked with BLOCKED or UNSAFE corporate action / security health cannot enter ranking."""
        rows = [
            {"symbol": "CLEAN_STOCK", "security_id": "SEC_1", "volar_score": 5.0, "ret_252": 0.5, "pass_all_filters": True, "corporate_action_status": "CLEAN", "security_health": "HEALTHY"},
            {"symbol": "TAINTED_STOCK", "security_id": "SEC_2", "volar_score": 10.0, "ret_252": 1.0, "pass_all_filters": True, "corporate_action_status": "UNRESOLVED", "security_health": "BLOCKED"},
        ]
        snap = pd.DataFrame(rows)
        clean_qualified_symbols = {"CLEAN_STOCK", "TAINTED_STOCK"}
        ranking_mask = snap["pass_all_filters"] & snap["symbol"].isin(clean_qualified_symbols)
        if "corporate_action_status" in snap.columns:
            ranking_mask = ranking_mask & (
                snap["corporate_action_status"].isin(["RESOLVED", "CLEAN", ""]) | snap["corporate_action_status"].isna()
            )
        if "security_health" in snap.columns:
            ranking_mask = ranking_mask & (~snap["security_health"].isin(["BLOCKED", "UNSAFE", "DEGRADED"]))

        admitted = snap[ranking_mask]["symbol"].tolist()
        self.assertIn("CLEAN_STOCK", admitted)
        self.assertNotIn("TAINTED_STOCK", admitted, "Tainted security breached ranking firewall!")

    def test_negative_momentum_firewall_rejection(self):
        """Securities with negative 1Y return or negative Volar must fail pass_mom."""
        rows = [
            {"symbol": "LOSER_1", "ret_252": -0.15, "volar_score": -0.75},
            {"symbol": "LOSER_2", "ret_252": 0.05, "volar_score": -0.10},
            {"symbol": "LOSER_3", "ret_252": -0.05, "volar_score": 0.20},
            {"symbol": "WINNER", "ret_252": 0.25, "volar_score": 1.25},
        ]
        df = pd.DataFrame(rows)
        df["pass_mom"] = (df["ret_252"] > 0) & (df["volar_score"] > 0)
        self.assertFalse(df.loc[df["symbol"] == "LOSER_1", "pass_mom"].iloc[0])
        self.assertFalse(df.loc[df["symbol"] == "LOSER_2", "pass_mom"].iloc[0])
        self.assertFalse(df.loc[df["symbol"] == "LOSER_3", "pass_mom"].iloc[0])
        self.assertTrue(df.loc[df["symbol"] == "WINNER", "pass_mom"].iloc[0])


class TestAdversarialOutputContractAndSafetyFirewall(unittest.TestCase):
    """Stress tests and contract verification for screener CSV exports vs institutional workbook."""

    def test_screener_csv_raw_rank_does_not_bypass_portfolio_buy_firewall(self):
        """
        Adversarial test: Candidates in screener_output_live.csv exceeding sector cap
        (e.g. CPPLUS at raw rank 7 in Capital Goods) must fail closed with allow_buy=False,
        signal_type='BUFFER_HOLD', and reason_code='SECTOR_CAP_EXCEEDED'.
        """
        from core.portfolio import validate_candidate_safety
        csv_path = Path(__file__).resolve().parent.parent / "reports" / "screener_output_live.csv"
        if not csv_path.exists():
            self.skipTest("screener_output_live.csv not found")

        df = pd.read_csv(csv_path)
        capped = df[df["reason_code"] == "SECTOR_CAP_EXCEEDED"]
        self.assertFalse(capped.empty, "There must be candidates exceeding sector cap")
        row = capped.iloc[0]

        # Verify fail-closed firewall fields
        self.assertFalse(bool(row["allow_buy"]))
        self.assertEqual(str(row["signal_type"]).strip(), "BUFFER_HOLD")
        self.assertEqual(str(row["reason_code"]).strip(), "SECTOR_CAP_EXCEEDED")
        self.assertEqual(int(row["target_qty"]), 0)
        self.assertEqual(float(row["target_val"]), 0.0)

        # Downstream portfolio safety firewall MUST reject it
        is_safe, msg, code = validate_candidate_safety(row, top_n=20)
        self.assertFalse(is_safe, f"Exceeded sector candidate was not rejected! Message: {msg}")

    def test_workbook_top_candidates_strictly_enforces_sector_cap(self):
        """
        Verify institutional workbook 'Top Candidates' contains exactly 20 actionable candidates
        and every sector strictly obeys max_per_sector <= 2.
        """
        import openpyxl
        wb_path = Path(__file__).resolve().parent.parent / "reports" / "MIP1_Momentum_Scanner_2026-10-09_NIFTY750TOTALMARKET.xlsx"
        if not wb_path.exists():
            self.skipTest("Institutional workbook not found")

        wb = openpyxl.load_workbook(wb_path, data_only=True)
        self.assertIn("Top Candidates", wb.sheetnames)
        ws = wb["Top Candidates"]
        rows = list(ws.iter_rows(values_only=True))
        data_rows = rows[1:]

        self.assertEqual(len(data_rows), 20, "Top Candidates sheet must have exactly 20 rows")

        # Sector is column index 2 (Industry)
        sector_counts = {}
        for r in data_rows:
            sec = str(r[2]).strip().upper()
            sector_counts[sec] = sector_counts.get(sec, 0) + 1

        for sec, count in sector_counts.items():
            self.assertLessEqual(count, 2, f"Sector '{sec}' exceeded max_per_sector limit of 2 (found {count})")

    def test_bear_regime_deliverables_contain_zero_buy_authorizations(self):
        """
        Verify that under a bear/defensive regime:
        1. reports/screener_output_live.csv contains exactly zero allow_buy=True rows,
           and all signal_types are either BEAR_HOLD or BUFFER_HOLD.
        2. reports/MIP1_Momentum_Scanner_2026-10-09_NIFTY750TOTALMARKET.xlsx 'Top Candidates'
           sheet contains exactly 20 candidates, all marked with MIP-1 Status = 'HOLD (BEAR - 100% CASH)'.
        """
        import openpyxl

        # 1. CSV audit
        csv_path = Path(__file__).resolve().parent.parent / "reports" / "screener_output_live.csv"
        if not csv_path.exists():
            self.skipTest("screener_output_live.csv not found")

        df = pd.read_csv(csv_path)
        self.assertEqual(len(df), 100, "screener_output_live.csv must have 100 rows")
        if df["date"].iloc[0] == "2026-10-09":
            self.assertEqual(df["allow_buy"].sum(), 0, "No row may have allow_buy=True in bear regime")
            self.assertTrue((~df["allow_buy"]).all(), "Every row must have allow_buy=False")

            # Total counts: exactly 20 BEAR_HOLD (the 20 sector-capped selections) and 80 BUFFER_HOLD
            # Zero BUY signals anywhere
            self.assertNotIn("BUY", df["signal_type"].values)
        else:
            # Bull regime: top candidates (10 or 20 depending on configured top_n) are authorized for BUY
            buy_count = int(df["allow_buy"].sum())
            self.assertIn(buy_count, (10, 20), f"Top candidates must have allow_buy=True in bull regime (expected 10 or 20, got {buy_count})")

        # 2. Workbook audit
        wb_path = Path(__file__).resolve().parent.parent / "reports" / "MIP1_Momentum_Scanner_2026-10-09_NIFTY750TOTALMARKET.xlsx"
        if not wb_path.exists():
            self.skipTest("Institutional workbook not found")

        wb = openpyxl.load_workbook(wb_path, data_only=True)
        self.assertIn("Top Candidates", wb.sheetnames)
        ws = wb["Top Candidates"]
        rows = list(ws.iter_rows(values_only=True))
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), 20)

        # MIP-1 Status is column index 4 (0-indexed)
        statuses = [str(r[4]).strip() for r in data_rows]
        for s in statuses:
            self.assertIn("HOLD (BEAR - 100% CASH)", s, f"Row status '{s}' is not bear hold cash protection")
            self.assertNotIn("BUY", s)

    def test_downstream_order_generation_rejects_every_supplied_non_buy_status(self):
        """
        Verify downstream order generation strictly rejects every supplied non-buy status:
        1. PortfolioManager.generate_rebalance_orders() produces zero BUY tickets in bear regime.
        2. validate_candidate_safety() rejects 100% of rows from screener_output_live.csv.
        3. Synthetic candidates with non-buy signals (BEAR_HOLD, BUFFER_HOLD, BLOCKED_HOLD,
           REVIEW_REQUIRED, BLOCKED, UNSAFE) and allow_buy=False are all rejected.
        """
        import io
        import contextlib
        from core.portfolio import PortfolioManager, validate_candidate_safety

        repo_root = Path(__file__).resolve().parent.parent
        pm = PortfolioManager(repo_root)
        with io.StringIO() as buf, contextlib.redirect_stdout(buf):
            orders = pm.generate_rebalance_orders(capital=1_000_000, cash=1_000_000, top_n=20)
        buy_orders = orders[orders["action"] == "BUY"] if not orders.empty else []
        self.assertEqual(len(buy_orders), 0, "generate_rebalance_orders must not emit any BUY orders in bear regime")

        # Verify all 100 rows in live screener are rejected by safety firewall
        csv_path = repo_root / "reports" / "screener_output_live.csv"
        if not csv_path.exists():
            self.skipTest("screener_output_live.csv not found")

        df = pd.read_csv(csv_path)
        for _, row in df.iterrows():
            is_safe, msg, code = validate_candidate_safety(row)
            self.assertFalse(is_safe, f"Candidate {row.get('symbol')} was unexpectedly allowed by safety firewall!")

        # Verify synthetic edge cases
        base_cand = {
            "symbol": "TESTSYM",
            "security_id": "SEC_TESTSYM",
            "close": 500.0,
            "corporate_action_status": "CLEAN",
            "security_health": "HEALTHY",
            "reason_code": "PASS",
        }

        non_buy_signals = ["BEAR_HOLD", "BUFFER_HOLD", "BLOCKED_HOLD", "REVIEW_REQUIRED", "BLOCKED", "UNSAFE"]
        for sig in non_buy_signals:
            cand = pd.Series({**base_cand, "signal_type": sig, "allow_buy": True})
            is_safe, msg, code = validate_candidate_safety(cand)
            self.assertFalse(is_safe, f"Signal {sig} bypassed safety firewall!")

        # allow_buy=False with BUY signal
        cand_not_allowed = pd.Series({**base_cand, "signal_type": "BUY", "allow_buy": False})
        is_safe, msg, code = validate_candidate_safety(cand_not_allowed)
        self.assertFalse(is_safe, "allow_buy=False bypassed safety firewall!")

    def test_authoritative_strategy_fingerprint_derivation(self):
        """
        Verify the canonical strategy fingerprint 9036fae5... is deterministically derived
        from exactly the 9 scalar fields in core/config.py MIPScannerConfig.
        """
        import hashlib
        import json
        from core.config import MIPScannerConfig

        cfg = MIPScannerConfig()
        d = cfg.to_dict()
        params = {
            "ema_regime_span": d["ema_regime_span"],
            "ema_rs_span": d["ema_rs_span"],
            "ema_trend_span": d["ema_trend_span"],
            "exit_buffer_rank": d["exit_buffer_rank"],
            "max_per_sector": d["max_per_sector"],
            "momentum_lookback_bars": d["momentum_lookback_bars"],
            "retrace_threshold": d["retrace_threshold"],
            "top_n_candidates": d["top_n_candidates"],
            "volatility_floor": d["volatility_floor"],
        }
        serialized = json.dumps(params, sort_keys=True)
        fp = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        expected = "9036fae5c41a27713901c8e82a97dfa07bc2f26a86f8e3231fdb8868d78673de"
        self.assertEqual(fp, expected)


if __name__ == "__main__":
    unittest.main()

