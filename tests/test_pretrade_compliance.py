"""
tests/test_pretrade_compliance.py - Unit Tests for Pre-Trade Compliance & SEBI Audit Suite
"""

import unittest
import pandas as pd
from compliance.pretrade_audit import PreTradeComplianceAuditor, ComplianceManifest


class TestPreTradeCompliance(unittest.TestCase):
    def setUp(self):
        self.auditor = PreTradeComplianceAuditor()

    def test_compliant_portfolio_passes_all_checks(self):
        # 20 stocks across 10 sectors (2 per sector), each ~50,000 INR out of 1,000,000 INR NAV
        candidates = []
        sectors = ["IT", "BANK", "AUTO", "PHARMA", "FMCG", "METALS", "ENERGY", "REALTY", "INFRA", "MEDIA"]
        for i, sec in enumerate(sectors):
            candidates.append({"symbol": f"SYM_{sec}_1", "sector": sec, "close": 1000.0, "target_val": 49000.0, "allow_buy": True})
            candidates.append({"symbol": f"SYM_{sec}_2", "sector": sec, "close": 500.0, "target_val": 49000.0, "allow_buy": True})

        df = pd.DataFrame(candidates)
        manifest = self.auditor.verify_pretrade_compliance(
            candidates_df=df,
            as_of_date="2026-10-16",
            total_portfolio_nav=1_000_000.0,
            available_cash=1_000_000.0,
            export_to_disk=False,
        )

        self.assertEqual(manifest.overall_status, "COMPLIANT")
        self.assertEqual(manifest.failed_checks, 0)
        self.assertGreater(len(manifest.sha256_seal), 32)

    def test_single_stock_concentration_limit_breach(self):
        # 1 stock holds 15% of NAV (breaching SEBI 10% limit)
        df = pd.DataFrame([
            {"symbol": "OVERWEIGHT_STOCK", "sector": "IT", "close": 1000.0, "target_val": 150000.0, "allow_buy": True},
            {"symbol": "NORMAL_STOCK", "sector": "BANK", "close": 500.0, "target_val": 50000.0, "allow_buy": True},
        ])

        manifest = self.auditor.verify_pretrade_compliance(
            candidates_df=df,
            as_of_date="2026-10-16",
            total_portfolio_nav=1_000_000.0,
            available_cash=1_000_000.0,
            export_to_disk=False,
        )

        self.assertEqual(manifest.overall_status, "NON_COMPLIANT")
        stock_check = next(r for r in manifest.check_results if r["check_name"] == "SEBI_SINGLE_STOCK_CONCENTRATION_LIMIT")
        self.assertFalse(stock_check["passed"])


if __name__ == "__main__":
    unittest.main()
