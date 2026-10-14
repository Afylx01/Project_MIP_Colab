"""
test_feature3_volatility_targeting.py - Contract & Unit Tests for Feature 3 (Volatility Targeting & Cash Shield)
Verifies:
1. EWMA volatility forecasting on benchmark return series.
2. Volatility targeting scalar bounded between min_exposure (0.20) and max_exposure (1.00).
3. Dynamic Cash Shield coupling with market breadth participation.
4. Strict fail-closed regime preservation (Close < 20 EMA produces scalar 0.0).
5. Integer whole-share target quantity scaling.
"""

import unittest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nextgen.volatility_targeting import (
    VolatilityTargetConfig,
    compute_ewma_realized_volatility,
    compute_volatility_target_scalar,
    compute_dynamic_cash_shield_scalar,
    scale_position_quantities_by_shield,
)


class TestFeature3VolatilityTargeting(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.T = 250
        # Normal volatility regime (12% annualized)
        self.normal_returns = pd.Series(np.random.normal(0.0005, 0.12 / np.sqrt(252), self.T))
        # High volatility regime (36% annualized)
        self.spike_returns = pd.Series(np.random.normal(0.0, 0.36 / np.sqrt(252), self.T))

    def test_ewma_volatility_estimation(self):
        """EWMA vol must track the true annualized dispersion."""
        ann_vol = compute_ewma_realized_volatility(self.normal_returns, lambda_decay=0.94)
        last_vol = ann_vol.iloc[-1]
        self.assertAlmostEqual(last_vol, 0.12, delta=0.03,
                               msg=f"Estimated EWMA vol {last_vol:.3f} deviates from expected 0.12")

    def test_volatility_target_scalar_scaling(self):
        """During high volatility spikes, scalar must decrease towards 0.20 floor."""
        scalar_normal = compute_volatility_target_scalar(self.normal_returns, target_vol=0.12)
        scalar_spike = compute_volatility_target_scalar(self.spike_returns, target_vol=0.12)

        self.assertGreaterEqual(scalar_normal.iloc[-1], 0.80)
        self.assertLessEqual(scalar_spike.iloc[-1], 0.50)
        self.assertGreaterEqual(scalar_spike.iloc[-1], 0.20)

    def test_strict_fail_closed_regime_shield(self):
        """When benchmark is in a bear regime (Close < 20 EMA), scalar MUST be 0.0."""
        # Bull regime
        scalar_bull = compute_dynamic_cash_shield_scalar(
            is_bull_regime=True,
            realized_vol=0.12,
            target_vol=0.12,
            breadth_ratio=0.85,
        )
        self.assertGreater(scalar_bull, 0.0)

        # Bear regime: MUST BE 0.0 (Cash Shield 100%)
        scalar_bear = compute_dynamic_cash_shield_scalar(
            is_bull_regime=False,
            realized_vol=0.12,
            target_vol=0.12,
            breadth_ratio=0.85,
        )
        self.assertEqual(scalar_bear, 0.0, "Bear regime did not produce 0.0 scalar")

    def test_integer_whole_share_scaling(self):
        """Position quantities must scale down cleanly as integers with zero fractional shares."""
        nominal_quantities = {"RELIANCE": 100, "INFY": 50, "TCS": 30}
        shield_scalar = 0.65

        scaled = scale_position_quantities_by_shield(nominal_quantities, shield_scalar)

        for sym, q in scaled.items():
            self.assertIsInstance(q, int)
            self.assertEqual(q, int(nominal_quantities[sym] * 0.65))

        self.assertEqual(scaled["RELIANCE"], 65)
        self.assertEqual(scaled["INFY"], 32)
        self.assertEqual(scaled["TCS"], 19)


if __name__ == "__main__":
    unittest.main()
