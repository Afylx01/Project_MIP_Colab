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

    def test_tearsheet_fails_closed_when_risk_metrics_unavailable(self):
        df = pd.DataFrame([
            {"rank": 1, "symbol": "STLTECH", "sector": "TELECOM", "close": 865.9, "target_qty": 9, "target_val": 7793.1, "volar_score": 5.55, "residual_alpha": 0.42, "signal_type": "BUY", "reason_code": "PASS", "delivery_action": "APPROVED"},
        ])
        out = self.temp_dir / "unavailable.html"
        InstitutionalTearsheetGenerator.generate_html_tearsheet(
            candidates_df=df,
            risk_metrics={"scenario_type": "UNAVAILABLE"},
            compliance_manifest=None,
            output_path=out,
        )
        content = out.read_text(encoding="utf-8")
        self.assertIn("RISK METRICS UNAVAILABLE", content)          # explicit disclosure
        self.assertNotIn("COMPLIANT", content)
        self.assertNotIn("E1_GOLD_SEAL", content)
        for fabricated in ["28.50", "1.35", "2.15", "1.48", "19.20", "1.85", "2.65", "4.12", "2.50"]:
            self.assertNotIn(fabricated, content)                  # no invented KPIs

    def test_seal_never_claims_pass_without_compliance_manifest(self):
        df = pd.DataFrame([
            {"rank": 1, "symbol": "STLTECH", "sector": "TELECOM", "close": 865.9, "target_qty": 9, "target_val": 7793.1, "volar_score": 5.55, "residual_alpha": 0.42, "signal_type": "BUY", "reason_code": "PASS", "delivery_action": "APPROVED"},
        ])
        valid_risk = {
            "cagr": 0.25,
            "annualized_volatility": 0.15,
            "sharpe_ratio": 1.20,
            "sortino_ratio": 1.80,
            "calmar_ratio": 1.10,
            "max_drawdown": 0.20,
            "var_95": 0.02,
            "cvar_95": 0.03,
            "ulcer_index": 2.5,
        }
        out_no_manifest = self.temp_dir / "no_manifest.html"
        InstitutionalTearsheetGenerator.generate_html_tearsheet(
            candidates_df=df,
            risk_metrics=valid_risk,
            compliance_manifest=None,
            output_path=out_no_manifest,
        )
        content_no = out_no_manifest.read_text(encoding="utf-8")
        self.assertNotIn("[PASS]", content_no)
        self.assertNotIn("Survivorship-Free Database [PASS]", content_no)
        self.assertNotIn("Verified", content_no)

        out_non_compliant = self.temp_dir / "non_compliant.html"
        InstitutionalTearsheetGenerator.generate_html_tearsheet(
            candidates_df=df,
            risk_metrics=valid_risk,
            compliance_manifest={"overall_status": "NON_COMPLIANT", "sha256_seal": "fedcba9876543210"},
            output_path=out_non_compliant,
        )
        content_non_comp = out_non_compliant.read_text(encoding="utf-8")
        self.assertIn("NON_COMPLIANT", content_non_comp)


if __name__ == "__main__":
    unittest.main()
