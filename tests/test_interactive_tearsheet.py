"""
tests/test_interactive_tearsheet.py - Unit Tests for Interactive HTML Tearsheet Generator
"""

import unittest
import tempfile
import shutil
from pathlib import Path
import pandas as pd
from reporting.interactive_tearsheet import InstitutionalTearsheetGenerator


class TestInteractiveTearsheet(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_html_tearsheet_creates_standalone_file(self):
        df = pd.DataFrame([
            {"rank": 1, "symbol": "STLTECH", "sector": "TELECOM", "close": 865.9, "target_qty": 9, "target_val": 7793.1, "volar_score": 5.55, "residual_alpha": 0.42, "signal_type": "BUY", "reason_code": "PASS", "delivery_action": "APPROVED"},
            {"rank": 2, "symbol": "CUPID", "sector": "FMCG", "close": 353.7, "target_qty": 29, "target_val": 10257.3, "volar_score": 3.93, "residual_alpha": 0.28, "signal_type": "BUY", "reason_code": "PASS", "delivery_action": "APPROVED"},
        ])

        risk_metrics = {
            "cagr": 0.295,
            "annualized_volatility": 0.175,
            "sharpe_ratio": 1.42,
            "sortino_ratio": 2.21,
            "calmar_ratio": 1.55,
            "max_drawdown": 0.185,
            "var_95": 0.019,
            "cvar_95": 0.027,
            "ulcer_index": 3.85,
            "information_ratio": 0.92,
            "beta": 0.88,
            "r_squared": 0.84,
        }

        compliance_manifest = {
            "overall_status": "COMPLIANT",
            "sha256_seal": "0123456789abcdef0123456789abcdef",
        }

        out_path = self.temp_dir / "test_tearsheet.html"
        result_path = InstitutionalTearsheetGenerator.generate_html_tearsheet(
            candidates_df=df,
            risk_metrics=risk_metrics,
            compliance_manifest=compliance_manifest,
            universe="NIFTY750",
            benchmark="NIFTY50",
            as_of_date="2026-10-16",
            output_path=out_path,
        )

        self.assertTrue(result_path.exists())
        content = result_path.read_text(encoding="utf-8")
        self.assertIn("MIP Institutional Momentum Strategy Tearsheet", content)
        self.assertIn("STLTECH", content)
        self.assertIn("NIFTY50", content)
        self.assertIn("COMPLIANT", content)
        self.assertIn("Ulcer Index", content)
        self.assertIn("data-theme=\"dark\"", content)


if __name__ == "__main__":
    unittest.main()
