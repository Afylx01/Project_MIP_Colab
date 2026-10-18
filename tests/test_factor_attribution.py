"""
tests/test_factor_attribution.py - Unit Tests for Brinson-Fachler Attribution Engine
"""

import unittest
import pandas as pd
import numpy as np
from analytics.factor_attribution import BrinsonFachlerEngine


class TestFactorAttributionEngine(unittest.TestCase):
    def test_single_period_exact_identity(self):
        # 3 sectors
        pw = {"IT": 0.40, "BANK": 0.40, "AUTO": 0.20}
        pr = {"IT": 0.10, "BANK": -0.05, "AUTO": 0.02}

        bw = {"IT": 0.30, "BANK": 0.50, "AUTO": 0.20}
        br = {"IT": 0.08, "BANK": -0.02, "AUTO": 0.01}

        df = BrinsonFachlerEngine.compute_single_period(pw, pr, bw, br)

        # Expected total returns
        total_p = sum(pw[k] * pr[k] for k in pw)
        total_b = sum(bw[k] * br[k] for k in bw)
        expected_active = total_p - total_b

        sum_alloc = df["allocation_effect"].sum()
        sum_select = df["selection_effect"].sum()
        sum_inter = df["interaction_effect"].sum()
        sum_active = df["total_active_return"].sum()

        self.assertAlmostEqual(sum_active, expected_active, places=5)
        self.assertAlmostEqual(sum_alloc + sum_select + sum_inter, expected_active, places=5)

    def test_multi_period_linking_preserves_cumulative_active_spread(self):
        # 2 periods
        p1 = BrinsonFachlerEngine.compute_single_period(
            {"IT": 0.5, "BANK": 0.5}, {"IT": 0.05, "BANK": 0.02},
            {"IT": 0.3, "BANK": 0.7}, {"IT": 0.03, "BANK": 0.01},
        )
        p2 = BrinsonFachlerEngine.compute_single_period(
            {"IT": 0.6, "BANK": 0.4}, {"IT": -0.02, "BANK": 0.04},
            {"IT": 0.3, "BANK": 0.7}, {"IT": -0.01, "BANK": 0.03},
        )

        rp_list = [0.035, 0.004]
        rb_list = [0.016, 0.018]

        cum_rp = (1.0 + rp_list[0]) * (1.0 + rp_list[1]) - 1.0
        cum_rb = (1.0 + rb_list[0]) * (1.0 + rb_list[1]) - 1.0
        expected_active_spread = cum_rp - cum_rb

        linked_df = BrinsonFachlerEngine.link_multi_period_menchero([p1, p2], rp_list, rb_list)
        total_cum_active = linked_df["cumulative_total_active"].sum()

        self.assertAlmostEqual(total_cum_active, expected_active_spread, places=5)


if __name__ == "__main__":
    unittest.main()
