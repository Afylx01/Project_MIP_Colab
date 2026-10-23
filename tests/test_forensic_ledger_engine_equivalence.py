"""
tests/test_forensic_ledger_engine_equivalence.py
Tests verifying that generate_window_trade_ledger faithfully replicates
sim_kernel.c mechanics, sizing, sector capping, valid price masking,
and financial accounting invariants.
"""

import sys
import unittest
import json
from pathlib import Path
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from brute_force.cube_builder import TensorCubeContainer
from brute_force.bridge import NativeBruteForceEngine
from brute_force.grid import (
    FILTER_SECTOR_CAP,
    FILTER_RS,
    FILTER_TREND,
    FILTER_RETRACE,
    FILTER_REGIME,
    FILTER_VOL_TARGETING,
    FILTER_RESIDUAL_MOM,
)
from scripts.forensic_integrity_audit import (
    generate_window_trade_ledger,
    compute_comparability,
    compute_calmar,
)


class TestForensicLedgerEngineEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = NativeBruteForceEngine()

    def test_equal_weight_two_slots_allocates_fifty_percent_each(self):
        """1.1 Cube: 6 dates, symbols ['A','B'], open=close=100.0, monthly schedule [0,3],
        volar[0,0,:]=1.0, volar[0,3:,:]=0.0. Params: top_n=2, friction=0, sizing=equal_weight.
        Must execute exactly 2 BUYs, 500 shares each, spending all 100k cash."""
        num_dates = 6
        px = np.full((num_dates, 2), 100.0, dtype=np.float32)
        reb = np.array([0, 3], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, num_dates, 2), dtype=np.float32)
        volar[0, 0, :] = 1.0

        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["A", "B"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        params = {
            "schedule_idx": 1,
            "top_n": 2,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99,
        }
        res = generate_window_trade_ledger(cube, params, 0, 5)
        buys = [t for t in res["trades"] if t["type"] == "BUY"]
        self.assertEqual(len(buys), 2)
        self.assertEqual({t["symbol"] for t in buys}, {"A", "B"})
        self.assertEqual([t["shares"] for t in buys], [500, 500])
        self.assertEqual(buys[-1]["cash_after"], 0.0)

    def test_ledger_does_not_enter_on_masked_execution_bar(self):
        """1.2 Cube: 5 dates, 1 symbol, valid_price_mask[1, 0]=0.
        Must not BUY on masked execution bar and engine trades must be 0."""
        num_dates = 5
        px = np.full((num_dates, 1), 100.0, dtype=np.float32)
        reb = np.array([0], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, 1), dtype=np.float32)
        mask = np.ones((num_dates, 1), dtype=np.uint8)
        mask[1, 0] = 0  # Execution bar masked

        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["A"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        params = {
            "schedule_idx": 1,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99,
        }
        res = generate_window_trade_ledger(cube, params, 0, 4)
        buys = [t for t in res["trades"] if t["type"] == "BUY"]
        self.assertEqual(len(buys), 0)

    def test_ledger_enforces_sector_cap(self):
        """1.3 Cube: 3 symbols, sector_ids=[0,0,1], volar=[3,2,1], max_per_sector=1.
        S1 must be blocked by sector cap, BUY symbols must be {'A', 'C'}."""
        num_dates = 5
        px = np.full((num_dates, 3), 100.0, dtype=np.float32)
        reb = np.array([0], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, num_dates, 3), dtype=np.float32)
        volar[0, 0, :] = [3.0, 2.0, 1.0]

        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["S0", "S1", "S2"],
            sector_ids=np.array([0, 0, 1], dtype=np.uint8),
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        params = {
            "schedule_idx": 1,
            "top_n": 3,
            "filter_flags": FILTER_SECTOR_CAP,
            "max_per_sector": 1,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
        }
        res = generate_window_trade_ledger(cube, params, 0, 4)
        buys = [t for t in res["trades"] if t["type"] == "BUY"]
        self.assertEqual({t["symbol"] for t in buys}, {"S0", "S2"})

    def test_ledger_atr_risk_parity_matches_kernel_share_count(self):
        """1.4 ATR risk parity sizing matches kernel share count."""
        num_dates = 5
        px = np.full((num_dates, 1), 100.0, dtype=np.float32)
        atr = np.full((num_dates, 1), 5.0, dtype=np.float32)
        reb = np.array([0], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, 1), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["S0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            atr_14=atr,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        params = {
            "schedule_idx": 1,
            "top_n": 1,
            "sizing_mode": "atr_risk_parity",
            "risk_per_trade_pct": 1.0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99,
        }
        res = generate_window_trade_ledger(cube, params, 0, 4)
        buys = [t for t in res["trades"] if t["type"] == "BUY"]
        self.assertEqual(len(buys), 1)
        self.assertEqual(buys[0]["shares"], 100)

    def test_ledger_rejects_invalid_configuration(self):
        """1.5 Ledger raises ValueError on invalid configurations."""
        num_dates = 5
        px = np.full((num_dates, 1), 100.0, dtype=np.float32)
        reb = np.array([0], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["S0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        base = {
            "schedule_idx": 1,
            "top_n": 1,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
        }

        # initial_capital <= 0
        with self.assertRaises(ValueError):
            generate_window_trade_ledger(cube, {**base, "initial_capital": 0.0}, 0, 4)

        # friction_bps < 0
        with self.assertRaises(ValueError):
            generate_window_trade_ledger(cube, {**base, "friction_bps": -1.0}, 0, 4)

        # top_n <= 0
        with self.assertRaises(ValueError):
            generate_window_trade_ledger(cube, {**base, "top_n": 0}, 0, 4)

        # be_idx < bs_idx
        with self.assertRaises(ValueError):
            generate_window_trade_ledger(cube, base, 4, 0)

    def test_ledger_cash_conservation(self):
        """1.6 Cash conservation: cash_after matches cash_before - cost for BUY, + proceeds for SELL."""
        num_dates = 10
        px = np.full((num_dates, 2), 100.0, dtype=np.float32)
        reb = np.array([0, 5], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, 2), dtype=np.float32)
        volar[0, 5:, :] = 0.0  # drop score to trigger exit

        cube = TensorCubeContainer(
            dates=[f"2020-01-{i+1:02d}" for i in range(num_dates)],
            symbols=["S0", "S1"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200],
        )
        params = {
            "schedule_idx": 1,
            "top_n": 2,
            "initial_capital": 100_000.0,
            "friction_bps": 15.0,
            "slippage_bps": 5.0,
            "sizing_mode": "equal_weight",
            "exit_buffer_rank": 1,
        }
        res = generate_window_trade_ledger(cube, params, 0, 9)
        fric_rate = 20.0 / 10000.0

        for t in res["trades"]:
            if t["type"] == "BUY":
                expected = t["cash_before"] - (t["shares"] * t["price"] * (1.0 + fric_rate))
                self.assertAlmostEqual(t["cash_after"], round(float(expected), 2), places=2)
                self.assertGreaterEqual(t["cash_after"], 0.0)
            elif t["type"] == "SELL":
                expected = t["cash_before"] + (t["shares"] * t["price"] * (1.0 - fric_rate))
                self.assertAlmostEqual(t["cash_after"], round(float(expected), 2), places=2)
                self.assertGreaterEqual(t["cash_after"], 0.0)

    def test_no_hardcoded_2008_drawdown_values(self):
        """1.10 Verify no literal hardcoded 43.18, 18.05, or 17.53 strings in forensic_integrity_audit.py."""
        audit_src = (PROJECT_ROOT / "scripts" / "forensic_integrity_audit.py").read_text()
        self.assertNotIn("43.18", audit_src)
        self.assertNotIn("18.05", audit_src)
        self.assertNotIn("17.53", audit_src)

    def test_compute_comparability_flags(self):
        """1.11 Verify comparability helper matches required criteria."""
        comp, red = compute_comparability(223, 164, 23, 82, 0.0, 0.0)
        self.assertFalse(comp)
        self.assertIsNone(red)

        comp, red = compute_comparability(224, 224, 22, 22, 26.29, 14.91)
        self.assertTrue(comp)
        self.assertAlmostEqual(red, 11.38, places=2)

    def test_calmar_from_row_zero_drawdown_no_zerodivision(self):
        """1.12 Calmar calculation avoids ZeroDivisionError when max drawdown is 0."""
        row = {"calmar_ratio": 1.0, "max_drawdown_pct": 0.0, "cagr_pct": 0.0}
        self.assertEqual(compute_calmar(row), 1.0)
        row2 = {"max_drawdown_pct": 0.0, "cagr_pct": 10.0}
        self.assertEqual(compute_calmar(row2), 0.0)

    def test_retained_holdings_valued_at_sig_close_in_sizing(self):
        """1.13 Verify retained holdings are valued at sig_close (matching sim_kernel.c:413)
        when computing investable capital for new entrants."""
        num_dates, num_syms = 8, 3
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        # Retained stock A gaps: sig_close(d4)=200.0, exec_open(d5)=100.0
        px[4, 0] = 200.0
        px[5, 0] = 100.0
        # Exited stock B sells at 200.0
        px[5, 1] = 200.0

        reb = np.array([0, 4], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, num_dates, num_syms), dtype=np.float32)
        volar[0, 0, :] = 1.0
        volar[0, 4, 0] = 1.0  # Retain A
        volar[0, 4, 1] = 0.0  # Exit B
        volar[0, 4, 2] = 1.0  # Enter C

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["A", "B", "C"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "schedule_idx": 1,
            "top_n": 2,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 7)
        c_buys = [t for t in ledger["trades"] if t["type"] == "BUY" and t["symbol"] == "C"]
        self.assertEqual(len(c_buys), 1)
        # Under sig_close valuation: capital = 100k cash + 500 * 200.0 = 200k.
        # Alloc per stock = 200k / 2 = 100k. C price = 100.0 -> 1000 shares.
        self.assertEqual(c_buys[0]["shares"], 1000)

    def test_final_session_masked_holding_forward_fills_prior_close(self):
        """1.14 sim_kernel.c forward-fills prior close when a held stock is masked on final session."""
        num_dates, num_syms = 10, 2
        dates = [f"2020-03-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        # Corrupt unmasked price on final session
        px[num_dates - 1, 0] = 999.0
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)
        mask[num_dates - 1, 0] = 0  # SYM0 masked on final session

        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, num_dates, num_syms), dtype=np.float32)
        volar[0, 0, :] = 1.0

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0", "SYM1"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "top_n": 2,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "VALID")
        self.assertFalse(row["data_insufficient"])
        # With SYM0 forward-filled to 100.0 on final session, ending equity is exactly 100k
        self.assertEqual(row["ending_equity"], 100_000.0)

    def test_final_session_delisted_zero_close_preserves_total_loss(self):
        """1.15 sim_kernel.c preserves legitimate total loss (ending_equity=0) when holding delists (mask=0, px=0)."""
        num_dates, num_syms = 10, 1
        dates = [f"2020-03-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        px[-1, 0] = 0.0  # Delisted price
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)
        mask[-1, 0] = 0  # Delisted on final session

        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, num_syms), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "VALID")
        self.assertEqual(row["ending_equity"], 0.0)
        self.assertEqual(row["max_drawdown"], 100.0)

    def test_final_session_unmasked_zero_close_fails_closed(self):
        """1.15b Unmasked zero close on final session is corrupt data and fails closed as DATA_INSUFFICIENT."""
        num_dates, num_syms = 10, 1
        dates = [f"2020-03-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        px[-1, 0] = 0.0  # Unmasked zero price
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)

        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, num_syms), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])

    def test_masked_final_bar_with_nan_prior_close_fails_closed(self):
        """1.16 sim_kernel.c fails closed (DATA_INSUFFICIENT) when held symbol has NaN daily close."""
        num_dates, num_syms = 10, 2
        dates = [f"2020-03-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        px[num_dates - 2, 0] = np.nan  # prior close non-finite
        px[num_dates - 1, 0] = np.nan  # final close non-finite
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)
        mask[num_dates - 1, 0] = 0  # SYM0 masked on final bar

        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, num_syms), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0", "SYM1"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "top_n": 2,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])
        self.assertEqual(row["ending_equity"], 0.0)
        self.assertTrue(np.isnan(row["cagr"]))

    def test_all_holdings_masked_on_final_session_fails_closed(self):
        """1.17 When all holdings are masked on the final session, engine fails closed as DATA_INSUFFICIENT."""
        num_dates, num_syms = 10, 1
        dates = [f"2020-03-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)
        mask[num_dates - 1, 0] = 0  # Sole held stock masked on final bar

        reb = np.array([0, num_dates - 1], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, num_syms), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": num_dates - 1,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])

    def test_validity_must_not_depend_on_post_window_bar(self):
        """1.18 Point-in-time invariant: simulation status must never look ahead to post-window bars."""
        T = 31
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        reb = np.array([0, 29], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}

        px_a = np.full((T, 1), 100.0, dtype=np.float32)
        px_a[29, 0] = 0.0  # unmasked zero at day 29
        px_a[30, 0] = 100.0  # post-window bar is 100.0

        px_b = np.full((T, 1), 100.0, dtype=np.float32)
        px_b[29, 0] = 0.0  # unmasked zero at day 29
        px_b[30, 0] = 0.0  # post-window bar is 0.0

        mask = np.ones((T, 1), dtype=np.uint8)
        volar = np.ones((1, T, 1), dtype=np.float32)

        cube_a = TensorCubeContainer(
            dates=dates, symbols=["SYM0"], schedule_indices_map=sched,
            open_px=px_a, close_px=px_a, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        cube_b = TensorCubeContainer(
            dates=dates, symbols=["SYM0"], schedule_indices_map=sched,
            open_px=px_b, close_px=px_b, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )

        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 29,
            "top_n": 1, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        row_a = self.engine.run_sweep(cube_a, [param]).iloc[0]
        row_b = self.engine.run_sweep(cube_b, [param]).iloc[0]

        self.assertEqual(row_a["status"], "DATA_INSUFFICIENT")
        self.assertEqual(row_b["status"], "DATA_INSUFFICIENT")
        self.assertEqual(row_a["ending_equity"], row_b["ending_equity"])
        self.assertEqual(row_a["ending_equity"], 0.0)

    def test_post_delisting_masked_zero_is_written_off_not_valued_at_cost(self):
        """1.19 Masked zero bars (delisted) must be written off to 0.0, not carried at buy_px cost."""
        T = 30
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 2), 100.0, dtype=np.float32)
        # B is delisted on days 20-29: open=close=0.0
        px[20:, 1] = 0.0

        mask = np.ones((T, 2), dtype=np.uint8)
        mask[20:, 1] = 0  # B masked on days 20-29

        reb = np.array([0, 29], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, T, 2), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates, symbols=["A", "B"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 29,
            "top_n": 2, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "VALID")
        self.assertEqual(row["ending_equity"], 50_000.0)
        self.assertEqual(row["max_drawdown"], 50.0)

    def test_no_sell_fill_on_masked_execution_bar(self):
        """1.20 Orders must never execute fills on masked (halted) execution bars."""
        T = 15
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        symbols = ["SYM0", "SYM1"]
        px = np.full((T, 2), 100.0, dtype=np.float32)
        mask = np.ones((T, 2), dtype=np.uint8)
        mask[5, 0] = 0  # SYM0 halted on execution day 5 (SYM1 active)

        # Rebalances: day 0 (buy both), day 4 (SYM0 exit triggered -> exec day 5 deferred), day 9 (next tradeable rebalance)
        reb = np.array([0, 4, 9], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 2), dtype=np.float32)
        volar[0, 0, :] = 1.0  # Buy both at day 0
        volar[0, 4, 0] = 0.0  # SYM0 exit triggered at day 4
        volar[0, 4, 1] = 1.0  # SYM1 retained at day 4
        volar[0, 9, 0] = 0.0  # SYM0 exit executes at day 9 (exec day 10)
        volar[0, 9, 1] = 1.0  # SYM1 retained at day 9

        cube = TensorCubeContainer(
            dates=dates, symbols=symbols, schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "schedule_idx": 1, "top_n": 2, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 14)
        day5_sells = [t for t in ledger["trades"] if t["type"] == "SELL" and t["date"] == dates[5]]
        self.assertEqual(len(day5_sells), 0, "Must never execute SELL on masked execution bar")
        day10_sells = [t for t in ledger["trades"] if t["type"] == "SELL" and t["date"] == dates[10]]
        self.assertEqual(len(day10_sells), 1, "Deferred sell must execute on day 10")

        # Native engine check: run is VALID (not data_insufficient) because SYM1 was active!
        param["param_id"] = 1
        param["start_date_idx"] = 0
        param["end_date_idx"] = 14
        row = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(row["status"], "VALID")
        self.assertFalse(row["data_insufficient"])
        # Deferred exit executes on day 10 (rebalance 9 + 1)
        self.assertEqual(row["total_trades"], 1)

    def test_no_sell_fill_on_masked_execution_bar_single_symbol(self):
        """Single-symbol variant: halted execution bar defers sell; with no further rebalance, total_trades == 0."""
        T = 10
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 1), 100.0, dtype=np.float32)
        mask = np.ones((T, 1), dtype=np.uint8)
        mask[5, 0] = 0  # Halted on day 5

        reb = np.array([0, 4], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 1), dtype=np.float32)
        volar[0, 0, 0] = 1.0  # Buy day 0
        volar[0, 4, 0] = 0.0  # Exit day 4 -> exec day 5 (halted)

        cube = TensorCubeContainer(
            dates=dates, symbols=["SYM0"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 9,
            "top_n": 1, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 9)
        day5_sells = [t for t in ledger["trades"] if t["type"] == "SELL" and t["date"] == dates[5]]
        self.assertEqual(len(day5_sells), 0)
        self.assertEqual(len([t for t in ledger["trades"] if t["type"] == "SELL"]), 0)

        row = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(row["total_trades"], 0)

    def test_delisted_holding_excluded_from_sizing_capital_in_both_engines(self):
        """1.23 Written-off delisted holding must not contribute buy_px to sizing capital in either engine."""
        T = 40
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        symbols = ["A", "B", "C"]
        px = np.full((T, 3), 100.0, dtype=np.float32)
        mask = np.ones((T, 3), dtype=np.uint8)
        # B delists from day 10 onward
        px[10:, 1] = 0.0
        mask[10:, 1] = 0
        # C price jumps to 300 on days 25-39
        px[25:, 2] = 300.0

        reb = np.array([0, 10, 20, 30], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 3), dtype=np.float32)
        # Day 0: Buy A and B
        volar[0, 0, 0] = 1.0
        volar[0, 0, 1] = 1.0
        volar[0, 0, 2] = 0.0
        # Day 10: Retain A, B exits/delists
        volar[0, 10, 0] = 1.0
        volar[0, 10, 1] = 0.0
        volar[0, 10, 2] = 0.0
        # Day 20: Retain A, Enter C
        volar[0, 20, 0] = 1.0
        volar[0, 20, 1] = 0.0
        volar[0, 20, 2] = 1.0

        cube = TensorCubeContainer(
            dates=dates, symbols=symbols, schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 30,
            "top_n": 3, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 30)
        c_buys = [t for t in ledger["trades"] if t["type"] == "BUY" and t["symbol"] == "C"]
        self.assertEqual(len(c_buys), 1)
        self.assertEqual(c_buys[0]["shares"], 222)

        res = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(res["status"], "VALID")
        self.assertFalse(res["data_insufficient"])
        self.assertEqual(res["ending_equity"], 111_100.0)

    def test_engine_nonfinite_exit_price_fails_closed(self):
        """1.24 sim_kernel.c fails closed when exit execution price is non-finite (Inf/NaN)."""
        T = 10
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 2), 100.0, dtype=np.float32)
        px[5, 0] = np.inf  # Non-finite on exec day 5
        mask = np.ones((T, 2), dtype=np.uint8)

        reb = np.array([0, 4, 9], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 2), dtype=np.float32)
        volar[0, 0, :] = 1.0
        volar[0, 4, 0] = 0.0  # Exit SYM0
        volar[0, 4, 1] = 1.0  # Retain SYM1

        cube = TensorCubeContainer(
            dates=dates, symbols=["SYM0", "SYM1"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 9,
            "top_n": 2, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        row = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])
        self.assertTrue(np.isnan(row["cagr"]))
        self.assertEqual(row["ending_equity"], 0.0)

    def test_engine_unmasked_zero_exit_price_fails_closed(self):
        """1.25 sim_kernel.c fails closed when unmasked execution bar has zero price (corrupt data)."""
        T = 10
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 2), 100.0, dtype=np.float32)
        px[5, 0] = 0.0  # Unmasked zero price on exec day 5
        mask = np.ones((T, 2), dtype=np.uint8)

        reb = np.array([0, 4, 9], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 2), dtype=np.float32)
        volar[0, 0, :] = 1.0
        volar[0, 4, 0] = 0.0  # Exit SYM0
        volar[0, 4, 1] = 1.0  # Retain SYM1

        cube = TensorCubeContainer(
            dates=dates, symbols=["SYM0", "SYM1"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 9,
            "top_n": 2, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        row = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])

        ledger = generate_window_trade_ledger(cube, param, 0, 9)
        self.assertTrue(ledger.get("data_insufficient", False))

    def test_ledger_nonfinite_exit_prices_fail_closed(self):
        """1.21 Ledger must fail closed (data_insufficient) on non-finite execution prices."""
        T = 10
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 1), 100.0, dtype=np.float32)
        px[5, 0] = np.inf  # Non-finite price on execution day 5

        reb = np.array([0, 4, 9], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 1), dtype=np.float32)
        volar[0, 0, 0] = 1.0  # Buy
        volar[0, 4, 0] = 0.0  # Exit

        cube = TensorCubeContainer(
            dates=dates, symbols=["SYM0"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "schedule_idx": 1, "top_n": 1, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 9)
        self.assertTrue(ledger.get("data_insufficient", False))
        zero_sells = [t for t in ledger["trades"] if t["type"] == "SELL" and t["price"] == 0.0]
        self.assertEqual(len(zero_sells), 0)

    def test_midperiod_unmasked_zero_close_fails_closed(self):
        """1.22 Point-in-time invariant: unmasked zero close fails closed as DATA_INSUFFICIENT."""
        num_dates, num_syms = 30, 1
        dates = [f"2020-01-{i+1:02d}" for i in range(num_dates)]
        px = np.full((num_dates, num_syms), 100.0, dtype=np.float32)
        px[10, 0] = 0.0  # Mid-period unmasked zero on day 10
        mask = np.ones((num_dates, num_syms), dtype=np.uint8)

        reb = np.array([0, 29], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, num_dates, num_syms), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates,
            symbols=["SYM0"],
            schedule_indices_map=sched,
            open_px=px,
            close_px=px,
            volar_cubes=volar,
            valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504],
            ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1,
            "schedule_idx": 1,
            "start_date_idx": 0,
            "end_date_idx": 29,
            "top_n": 1,
            "filter_flags": 0,
            "initial_capital": 100_000.0,
            "friction_bps": 0.0,
            "slippage_bps": 0.0,
            "sizing_mode": "equal_weight",
            "lookback_idx": 0,
            "ema_idx": 0,
            "exit_buffer_rank": 40,
            "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param])
        row = res.iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])
        self.assertEqual(row["ending_equity"], 0.0)

    def test_delisted_slot_is_freed_for_new_entrants(self):
        """1.26 Delisted holding's slot must be freed to allow new qualifying entrants."""
        T = 40
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        symbols = ["A", "B", "C", "D"]
        px = np.full((T, 4), 100.0, dtype=np.float32)
        mask = np.ones((T, 4), dtype=np.uint8)
        # B delists from day 10 onward
        px[10:, 1] = 0.0
        mask[10:, 1] = 0

        reb = np.array([0, 10, 20, 30], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 4), dtype=np.float32)
        # Day 0: Buy A and B
        volar[0, 0, 0] = 1.0
        volar[0, 0, 1] = 1.0
        # Day 10: Retain A, B delists
        volar[0, 10, 0] = 1.0
        # Day 20: Retain A, enter C and D
        volar[0, 20, 0] = 1.0
        volar[0, 20, 2] = 1.0
        volar[0, 20, 3] = 1.0

        cube = TensorCubeContainer(
            dates=dates, symbols=symbols, schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 30,
            "top_n": 3, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        ledger = generate_window_trade_ledger(cube, param, 0, 30)
        day21_buys = [t for t in ledger["trades"] if t["type"] == "BUY" and t["date"] == dates[21]]
        self.assertEqual(len(day21_buys), 2, "Both C and D must be bought, proving B's slot was freed")
        bought_syms = {t["symbol"] for t in day21_buys}
        self.assertEqual(bought_syms, {"C", "D"})

        res = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(res["status"], "VALID")
        self.assertFalse(res["data_insufficient"])
        # A, C, and D are active; ending equity reflects 2/3 invested (66,700) after B's 1/3 write-off
        self.assertAlmostEqual(res["ending_equity"], 66_700.0, delta=200.0)

    def test_engine_frees_delisted_slot_total_trades(self):
        """Delisted holding compaction records write-off trade count so engine reports all closed trades."""
        T = 40
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        symbols = ["A", "B", "C", "D"]
        px = np.full((T, 4), 100.0, dtype=np.float32)
        mask = np.ones((T, 4), dtype=np.uint8)
        px[10:, 1] = 0.0
        mask[10:, 1] = 0

        reb = np.array([0, 10, 20, 30], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 4), dtype=np.float32)
        volar[0, 0, 0] = 1.0
        volar[0, 0, 1] = 1.0
        volar[0, 10, 0] = 1.0
        volar[0, 20, 0] = 1.0
        volar[0, 20, 2] = 1.0
        volar[0, 20, 3] = 1.0

        cube = TensorCubeContainer(
            dates=dates, symbols=symbols, schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 35,
            "top_n": 3, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(res["total_trades"], 4, "Engine must count 4 closed trades: 1 delisted write-off (B) + 3 exits (A, C, D)")

    def test_engine_delisted_writeoff_populates_loss_statistics(self):
        """Delisted write-off must populate gross_losses and zero win rate when all closed positions are losses."""
        T = 40
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        symbols = ["A", "B", "C", "D"]
        px = np.full((T, 4), 100.0, dtype=np.float32)
        mask = np.ones((T, 4), dtype=np.uint8)
        px[10:, 1] = 0.0
        mask[10:, 1] = 0

        reb = np.array([0, 10, 20, 30], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.zeros((1, T, 4), dtype=np.float32)
        volar[0, 0, 0] = 1.0
        volar[0, 0, 1] = 1.0
        volar[0, 10, 0] = 1.0
        volar[0, 20, 0] = 1.0
        volar[0, 20, 2] = 1.0
        volar[0, 20, 3] = 1.0

        cube = TensorCubeContainer(
            dates=dates, symbols=symbols, schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 35,
            "top_n": 3, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        res = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(res["total_trades"], 4)
        self.assertEqual(res["winning_trades"], 0)
        self.assertEqual(res["profit_factor"], 0.0)

    def test_nextgen_sim_profit_factor_semantics(self):
        """nextgen_sim.py must emit inf for zero losses with positive gains, and sanitize to None for strict JSON serialization."""
        from brute_force.nextgen_sim import NextGenSimulationEngine
        from unittest.mock import MagicMock

        engine = object.__new__(NextGenSimulationEngine)
        cube = MagicMock()
        cube.lookback_values = [252]
        cube.ema_span_values = [200]
        cube.num_dates = 6
        cube.num_symbols = 1
        cube.num_rebalances = 3
        cube.rebalance_indices = np.array([0, 2, 4], dtype=np.int32)
        px_close = np.array([[100.0], [100.0], [120.0], [120.0], [120.0], [120.0]], dtype=np.float32)
        px_open = np.array([[100.0], [100.0], [120.0], [120.0], [120.0], [120.0]], dtype=np.float32)
        cube.close_px = px_close
        cube.open_px = px_open
        cube.high_cubes = [np.array([[100.0], [100.0], [200.0], [200.0], [200.0], [200.0]], dtype=np.float32)]
        cube.volar_cubes = [np.ones((6, 1), dtype=np.float32)]
        cube.ema_cubes = [np.full((6, 1), 90.0, dtype=np.float32)]
        cube.rs_pass_cubes = [np.ones((6, 1), dtype=bool)]
        cube.rebalance_weights = np.ones((6, 1), dtype=np.float32)
        cube.atr_14 = np.full((6, 1), 2.0, dtype=np.float32)
        cube.benchmark_regime = np.ones(6, dtype=np.int32)
        cube.sector_ids = [0]

        engine.cube = cube
        engine.composite_volar_252 = cube.volar_cubes[0]
        engine.realized_vol = np.full(6, 0.10, dtype=np.float32)
        engine.breadth_participation = np.ones(6, dtype=np.float32)
        engine.clv_mat = np.ones((6, 1), dtype=np.float32)
        engine.lookback_idx_252 = 0
        engine.ema_idx_200 = 0

        res = engine.run_single(
            lookback_idx=0,
            ema_idx=0,
            enable_residual_momentum=False,
            enable_volatility_targeting=False,
            enable_distribution_veto=False,
        )
        self.assertEqual(res["total_trades"], 1)
        self.assertEqual(res["winning_trades"], 1)
        self.assertEqual(res["profit_factor"], float("inf"))
        from scripts.forensic_integrity_audit import sanitize_json_obj
        sanitized = sanitize_json_obj(res)
        self.assertIsNone(sanitized["profit_factor"])
        json_str = json.dumps(sanitized, allow_nan=False)
        self.assertIsNone(json.loads(json_str)["profit_factor"])

    def test_ledger_entry_nonfinite_exec_price_fails_closed(self):
        """1.27 Entry execution bar with non-finite prices fails closed in both engine and ledger."""
        T = 10
        dates = [f"2020-01-{i+1:02d}" for i in range(T)]
        px = np.full((T, 1), 100.0, dtype=np.float32)
        px[1, 0] = np.nan  # Non-finite on exec day 1 for day 0 rebalance entry
        mask = np.ones((T, 1), dtype=np.uint8)

        reb = np.array([0, 5], dtype=np.int32)
        sched = {s: reb for s in ["weekly", "monthly", "quarterly", "half_yearly", "yearly"]}
        volar = np.ones((1, T, 1), dtype=np.float32)

        cube = TensorCubeContainer(
            dates=dates, symbols=["SYM0"], schedule_indices_map=sched,
            open_px=px, close_px=px, volar_cubes=volar, valid_price_mask=mask,
            lookback_values=[63, 126, 252, 504], ema_span_values=[20, 50, 100, 150, 200]
        )
        param = {
            "param_id": 1, "schedule_idx": 1, "start_date_idx": 0, "end_date_idx": 9,
            "top_n": 1, "filter_flags": 0, "initial_capital": 100_000.0,
            "friction_bps": 0.0, "slippage_bps": 0.0, "sizing_mode": "equal_weight",
            "lookback_idx": 0, "ema_idx": 0, "exit_buffer_rank": 40, "max_per_sector": 99
        }
        row = self.engine.run_sweep(cube, [param]).iloc[0]
        self.assertEqual(row["status"], "DATA_INSUFFICIENT")
        self.assertTrue(row["data_insufficient"])

        ledger = generate_window_trade_ledger(cube, param, 0, 9)
        self.assertTrue(ledger.get("data_insufficient", False))


if __name__ == "__main__":
    unittest.main()

