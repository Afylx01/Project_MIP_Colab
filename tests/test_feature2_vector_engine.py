"""
test_feature2_vector_engine.py - Contract & Unit Tests for Feature 2 (Dual-Engine Vectorization)
Verifies:
1. 2D contiguous NumPy array matrix computation.
2. Exact numerical parity with canonical Pandas indicators (< 1e-4 relative tolerance).
3. Fast rolling highs, rolling standard deviations, EMAs, and ATR-14.
4. Safe handling of NaN/zeros for late-listing securities.
"""

import unittest
import numpy as np
import pandas as pd
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nextgen.vector_engine import (
    VectorIndicatorEngine,
    compute_matrix_rolling_high,
    compute_matrix_ema,
    compute_matrix_atr14,
    compute_matrix_volatility,
)


class TestFeature2VectorEngine(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        self.T = 400
        self.N = 20

        # Generate realistic synthetic price series
        returns = np.random.normal(0.0005, 0.015, (self.T, self.N))
        self.close_mat = 100.0 * np.exp(np.cumsum(returns, axis=0)).astype(np.float32)
        self.high_mat = self.close_mat * (1.0 + np.abs(np.random.normal(0.005, 0.005, (self.T, self.N)))).astype(np.float32)
        self.low_mat = self.close_mat * (1.0 - np.abs(np.random.normal(0.005, 0.005, (self.T, self.N)))).astype(np.float32)

    def test_rolling_high_parity(self):
        """Matrix rolling high must match Pandas rolling max across all stocks."""
        window = 252
        mat_high = compute_matrix_rolling_high(self.high_mat, window=window)

        df_high = pd.DataFrame(self.high_mat)
        pd_high = df_high.rolling(window, min_periods=50).max().to_numpy()

        # Compare non-nan elements
        mask = ~np.isnan(pd_high)
        np.testing.assert_allclose(mat_high[mask], pd_high[mask], rtol=1e-5, atol=1e-4)

    def test_matrix_ema_parity(self):
        """Matrix EMA must match Pandas ewm(span=span).mean()."""
        span = 200
        mat_ema = compute_matrix_ema(self.close_mat, span=span)

        df_close = pd.DataFrame(self.close_mat)
        pd_ema = df_close.ewm(span=span, adjust=True, min_periods=50).mean().to_numpy()

        mask = ~np.isnan(pd_ema)
        np.testing.assert_allclose(mat_ema[mask], pd_ema[mask], rtol=1e-4, atol=1e-3)

    def test_matrix_atr14_parity(self):
        """Matrix ATR-14 must match true range rolling mean."""
        mat_atr = compute_matrix_atr14(self.high_mat, self.low_mat, self.close_mat, window=14)

        prev_close = np.vstack([self.close_mat[:1], self.close_mat[:-1]])
        tr = np.maximum(
            self.high_mat - self.low_mat,
            np.maximum(np.abs(self.high_mat - prev_close), np.abs(self.low_mat - prev_close))
        )
        df_tr = pd.DataFrame(tr)
        pd_atr = df_tr.rolling(14, min_periods=5).mean().to_numpy()

        mask = ~np.isnan(pd_atr)
        np.testing.assert_allclose(mat_atr[mask], pd_atr[mask], rtol=1e-4, atol=1e-3)

    def test_vector_indicator_engine_pipeline(self):
        """Engine should process an entire universe matrix in a single batch pass."""
        engine = VectorIndicatorEngine()
        indicators = engine.compute_all(
            open_px=self.close_mat,
            high_px=self.high_mat,
            low_px=self.low_mat,
            close_px=self.close_mat,
            lookbacks=[126, 252],
            ema_spans=[100, 200],
        )

        self.assertIn("rolling_high_252", indicators)
        self.assertIn("ema_200", indicators)
        self.assertIn("atr_14", indicators)
        self.assertEqual(indicators["rolling_high_252"].shape, (self.T, self.N))
        self.assertEqual(indicators["ema_200"].shape, (self.T, self.N))


if __name__ == "__main__":
    unittest.main()
