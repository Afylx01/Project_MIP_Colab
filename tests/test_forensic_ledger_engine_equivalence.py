"""
tests/test_forensic_ledger_engine_equivalence.py
Tests verifying that generate_window_trade_ledger faithfully replicates
sim_kernel.c mechanics, sizing, sector capping, valid price masking,
and financial accounting invariants.
"""

import sys
import unittest
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
        """1.10 Verify no literal hardcoded 43.18 or 18.05 strings in forensic_integrity_audit.py."""
        audit_src = (PROJECT_ROOT / "scripts" / "forensic_integrity_audit.py").read_text()
        self.assertNotIn("43.18", audit_src)
        self.assertNotIn("18.05", audit_src)

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


if __name__ == "__main__":
    unittest.main()

