"""
tests/test_liquidity_analytics.py - Unit Tests for Liquidity Profiling & Capacity Modeler
"""

import unittest
import pandas as pd
from analytics.liquidity_analytics import compute_liquidity_profile


class TestLiquidityAnalytics(unittest.TestCase):
    def setUp(self):
        self.orders = pd.DataFrame([
            {"symbol": "RELIANCE", "close": 2500.0, "target_qty": 40, "target_val": 100000.0, "delivery_qty": 1500000, "vol_252": 0.22},
            {"symbol": "TCS", "close": 3500.0, "target_qty": 30, "target_val": 105000.0, "delivery_qty": 800000, "vol_252": 0.18},
            {"symbol": "INFY", "close": 1800.0, "target_qty": 55, "target_val": 99000.0, "delivery_qty": 1200000, "vol_252": 0.24},
        ])

    def test_compute_liquidity_profile_keys_and_values(self):
        res = compute_liquidity_profile(self.orders, capital_inr=1_000_000.0)

        self.assertIn("portfolio_days_to_liquidate", res)
        self.assertIn("weighted_adv_participation_pct", res)
        self.assertIn("liquidity_bucket_distribution", res)
        self.assertIn("strategy_capacity_crores", res)
        self.assertIn("detailed_table", res)

        table = res["detailed_table"]
        self.assertEqual(len(table), 3)
        self.assertTrue((table["days_to_liquidate"] <= 1.0).all())
        self.assertIn("TIER-1 (Highly Liquid: <= 1d)", res["liquidity_bucket_distribution"])
        self.assertGreater(res["strategy_capacity_crores"], 0.0)


if __name__ == "__main__":
    unittest.main()
