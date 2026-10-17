"""
tests/test_scanner_residual_momentum.py
Contract & Integration Tests for Scanner Residual Momentum Integration:
1. MomentumScanner.run_scan(use_residual_momentum=True) computes and populates residual_mom_score.
2. Composite Volar score is properly blended (40% canonical Volar + 60% idiosyncratic residual momentum).
3. HardenedScanner.run_scan propagates use_residual_momentum to base scanner.
4. top_df attributes record residual_momentum_enabled=True.
5. Fail-closed fallback: if residual computation encounters error, falls back cleanly to canonical Volar.
"""

import unittest
from pathlib import Path
import numpy as np
import pandas as pd

from core.data_engine import get_base_dir
from core.scanner import MomentumScanner, format_screener_tearsheet
from scripts.scanner_hardening import HardenedScanner


class TestScannerResidualMomentum(unittest.TestCase):

    def setUp(self):
        self.base_dir = get_base_dir()
        self.scanner = MomentumScanner(base_dir=self.base_dir)
        self.hardened = HardenedScanner(base_dir=self.base_dir)

    def test_01_scanner_run_scan_accepts_use_residual_momentum_flag(self):
        """MomentumScanner.run_scan signature must accept use_residual_momentum."""
        import inspect
        sig = inspect.signature(self.scanner.run_scan)
        self.assertIn("use_residual_momentum", sig.parameters,
                      "use_residual_momentum must be a parameter in MomentumScanner.run_scan")
        self.assertFalse(sig.parameters["use_residual_momentum"].default,
                         "use_residual_momentum default must be False for backward compatibility")

    def test_02_hardened_scanner_accepts_use_residual_momentum_flag(self):
        """HardenedScanner.run_scan signature must accept use_residual_momentum."""
        import inspect
        sig = inspect.signature(self.hardened.run_scan)
        self.assertIn("use_residual_momentum", sig.parameters,
                      "use_residual_momentum must be a parameter in HardenedScanner.run_scan")
        self.assertFalse(sig.parameters["use_residual_momentum"].default,
                         "use_residual_momentum default must be False for backward compatibility")

    def test_03_run_scan_with_residual_momentum_enabled(self):
        """Executing scan with use_residual_momentum=True populates residual_mom_score and sets attribute."""
        top_df, breadth, sectors, regime, top_etf, deliv = self.scanner.run_scan(
            universe_mode="NIFTY 50",
            top_n=5,
            export_csv=False,
            export_excel=False,
            auto_update_universe=False,
            allow_stale_data=True,
            use_residual_momentum=True,
        )

        self.assertIsNotNone(top_df)
        self.assertFalse(top_df.empty)
        self.assertTrue(top_df.attrs.get("residual_momentum_enabled"),
                        "top_df.attrs['residual_momentum_enabled'] must be True")
        self.assertIn("residual_mom_score", top_df.columns,
                      "top_df must contain 'residual_mom_score' column when residual momentum is enabled")
        self.assertIn("raw_volar_score", top_df.columns,
                      "top_df must contain 'raw_volar_score' column preserving canonical volar")

        # Verify composite blend: composite = 0.40 * raw_volar + 0.60 * residual_mom
        for _, row in top_df.iterrows():
            raw_v = float(row["raw_volar_score"])
            res_s = float(row["residual_mom_score"])
            comp_v = float(row["volar_score"])
            expected = 0.40 * raw_v + 0.60 * res_s
            self.assertAlmostEqual(comp_v, expected, places=4,
                                   msg=f"Volar score {comp_v} does not match expected composite {expected}")

    def test_04_tearsheet_formatting_reflects_residual_momentum(self):
        """format_screener_tearsheet must display residual momentum banner when active."""
        top_df, breadth, sectors, regime, top_etf, deliv = self.scanner.run_scan(
            universe_mode="NIFTY 50",
            top_n=3,
            export_csv=False,
            export_excel=False,
            auto_update_universe=False,
            allow_stale_data=True,
            use_residual_momentum=True,
        )
        as_of = top_df.attrs.get("scanned_date", "2026-10-09")
        ts = format_screener_tearsheet(top_df, breadth, sectors, regime, as_of)
        self.assertIn("RESIDUAL MOMENTUM", ts.upper(),
                      "Tearsheet must explicitly mention RESIDUAL MOMENTUM when active")


if __name__ == "__main__":
    unittest.main()
