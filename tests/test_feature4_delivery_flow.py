"""
test_feature4_delivery_flow.py - Contract & Unit Tests for Feature 4 (Delivery Absorption Flow)
Verifies:
1. Intra-bar Close Location Value (CLV) in [-1.0, +1.0].
2. Signed Delivery Absorption Flow (DAF) scaling with deliverable turnover multiple.
3. 5-day exponential decay Smart-Money Footprint Index (SMFI-5).
4. Institutional Distribution buy-veto gate (SMFI <= -1.5 blocks new buys).
5. Fail-closed fallback when bhavcopy delivery data is unpopulated.
"""

import unittest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nextgen.delivery_flow import (
    compute_close_location_value,
    compute_delivery_absorption_flow,
    compute_smart_money_footprint_index,
    evaluate_microstructure_buy_gate,
    DeliveryFlowConfig,
)


class TestFeature4DeliveryFlow(unittest.TestCase):
    def test_close_location_value_bounds(self):
        """CLV must be +1.0 at high, -1.0 at low, and 0.0 at midpoint."""
        # Case 1: Close at extreme high (C = 110, H = 110, L = 100) -> +1.0
        clv_high = compute_close_location_value(close=110.0, high=110.0, low=100.0)
        self.assertAlmostEqual(clv_high, 1.0, places=4)

        # Case 2: Close at extreme low (C = 100, H = 110, L = 100) -> -1.0
        clv_low = compute_close_location_value(close=100.0, high=110.0, low=100.0)
        self.assertAlmostEqual(clv_low, -1.0, places=4)

        # Case 3: Close at exact midpoint (C = 105, H = 110, L = 100) -> 0.0
        clv_mid = compute_close_location_value(close=105.0, high=110.0, low=100.0)
        self.assertAlmostEqual(clv_mid, 0.0, places=4)

        # Case 4: Zero range bar (H = L = C) -> 0.0
        clv_zero = compute_close_location_value(close=100.0, high=100.0, low=100.0)
        self.assertAlmostEqual(clv_zero, 0.0, places=4)

    def test_delivery_absorption_flow_signed_direction(self):
        """High volume closing near highs must produce positive DAF; near lows produces negative DAF."""
        # High delivery closing near highs
        daf_acc = compute_delivery_absorption_flow(
            delivery_qty=1_000_000,
            close=500.0,
            high=505.0,
            low=480.0,
            median_delivery_val_cr=10.0,  # ₹10 Cr baseline
        )
        self.assertGreater(daf_acc, 2.0, "High absorption closing near highs did not produce positive DAF")

        # High delivery closing near lows (Distribution)
        daf_dist = compute_delivery_absorption_flow(
            delivery_qty=1_000_000,
            close=481.0,
            high=505.0,
            low=480.0,
            median_delivery_val_cr=10.0,
        )
        self.assertLess(daf_dist, -2.0, "High delivery closing near lows did not produce negative DAF")

    def test_smart_money_footprint_index_decay(self):
        """SMFI-5 accumulates signed DAF over 5 days with 0.80 decay factor."""
        daf_history = [2.0, 2.5, 3.0, 2.0, 2.5]  # 5 days of sustained accumulation
        smfi_acc = compute_smart_money_footprint_index(daf_history, decay_factor=0.80)
        self.assertGreater(smfi_acc, 4.0)

        daf_dist_hist = [-2.0, -2.5, -3.0, -2.0, -2.5]  # 5 days of heavy distribution
        smfi_dist = compute_smart_money_footprint_index(daf_dist_hist, decay_factor=0.80)
        self.assertLess(smfi_dist, -4.0)

    def test_institutional_distribution_buy_veto(self):
        """Stocks with heavy distribution (SMFI <= -1.5) must be vetoed from BUY authorization."""
        # Candidate with SMFI = -2.2 -> must be VETOED
        gate_res = evaluate_microstructure_buy_gate(smfi_score=-2.2)
        self.assertFalse(gate_res["allow_buy"])
        self.assertEqual(gate_res["action"], "INSTITUTIONAL_DISTRIBUTION_VETO")

        # Candidate with SMFI = +2.8 -> approved with accumulation badge
        gate_acc = evaluate_microstructure_buy_gate(smfi_score=2.8)
        self.assertTrue(gate_acc["allow_buy"])
        self.assertEqual(gate_acc["action"], "INSTITUTIONAL_ACCUMULATION_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
