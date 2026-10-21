"""
colab - Google Colab Minimal Cockpit, Staging & Interactive Dashboard Package for Project MIP
Eliminates notebook code clutter by modularizing cloud staging, live screener rendering,
and SIMD brute-force dashboard into maintainable, tested Python modules.
"""

from colab.environment import setup_colab_environment
from colab.screener import run_screener_view
from colab.dashboard import render_backtest_dashboard
from colab.portfolio_view import run_portfolio_rebalancer, run_market_diagnostics_view

__all__ = [
    "setup_colab_environment",
    "run_screener_view",
    "render_backtest_dashboard",
    "run_portfolio_rebalancer",
    "run_market_diagnostics_view",
]
