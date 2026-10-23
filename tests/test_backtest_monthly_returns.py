"""
tests/test_backtest_monthly_returns.py
Tests verifying empirical monthly returns invariant and trade log emission in LightweightBacktester.
"""

from pathlib import Path
import numpy as np
import pytest

from core.backtest import LightweightBacktester

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.integration
def test_lightweight_backtester_emits_one_return_per_monthly_rebalance(tmp_path):
    """Verify LightweightBacktester emits exactly one return per monthly rebalance (len = len(rebalance_months) - 1),
    that all returns are finite, that compound monthly returns match final_equity / initial_capital,
    and that trade_log_path points to the standardized reports directory."""
    db_file = PROJECT_ROOT / "data" / "universe.db"
    if not db_file.exists():
        pytest.skip("Integration test requires data/universe.db")

    bt = LightweightBacktester(base_dir=PROJECT_ROOT, output_dir=tmp_path)
    rebalance_months = [f"2023-{m:02d}" for m in range(1, 13)] + [f"2024-{m:02d}" for m in range(1, 13)]

    r = bt.run(start_date="2023-01-01", end_date="2024-12-31", top_n=10)

    # 1. Exactly len(rebalance_months) - 1 monthly returns (cadence invariant)
    assert len(r["monthly_returns"]) == len(rebalance_months) - 1, (
        f"Expected {len(rebalance_months) - 1} monthly returns for 24-month horizon, got {len(r['monthly_returns'])}"
    )

    # 2. All returns are finite
    rets_arr = np.array(r["monthly_returns"], dtype=float)
    assert np.all(np.isfinite(rets_arr)), "All monthly returns must be finite numbers"

    # 3. Compounded return identity: prod(1 + r_m) == final_equity / initial_capital
    compounded_ret = float(np.prod(1.0 + rets_arr))
    equity_ratio = float(r["final_equity"] / r["initial_capital"])
    assert abs(compounded_ret - equity_ratio) < 1e-6, (
        f"Compound monthly returns ({compounded_ret}) did not match equity ratio ({equity_ratio})"
    )

    # 4. Standardized trade log emission path
    assert r["trade_log_path"] == str(bt.output_dir / "trade_log.csv")
    assert Path(r["trade_log_path"]).exists()
