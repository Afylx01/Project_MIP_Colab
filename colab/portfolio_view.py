"""
colab/portfolio_view.py - Interactive Portfolio Rebalancer & Order Execution Cockpit for Google Colab
Provides interactive form widgets, Zerodha holdings input, friction breakdown, and visual execution tickets.
"""

import os
import sys
import json
from pathlib import Path
from typing import Optional, Dict, Any
import pandas as pd

try:
    from IPython.display import display, HTML
except ImportError:
    def display(obj):
        pass
    def HTML(data):
        return data

from core.portfolio import PortfolioManager
from core.breadth import MarketBreadthEngine
from core.sector_rotation import SectorRotationEngine
from core.data_engine import get_latest_date, get_base_dir


def run_portfolio_rebalancer(
    capital: float = 100000.0,
    top_n: int = 10,
    holdings_json_or_dict: Optional[Any] = None,
    sizing_mode: str = "atr_risk_parity",
    save_holdings: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Executes live portfolio rebalancing against latest screener candidates,
    respecting exit buffers, sector concentration caps, and statutory frictions.
    """
    base_dir = Path("/content/Project_MIP_Colab") if Path("/content/Project_MIP_Colab").exists() else get_base_dir()
    pm = PortfolioManager(base_dir)

    holdings = {}
    if holdings_json_or_dict:
        if isinstance(holdings_json_or_dict, dict):
            holdings = holdings_json_or_dict
        elif isinstance(holdings_json_or_dict, str):
            try:
                holdings = json.loads(holdings_json_or_dict)
            except Exception:
                import ast
                try:
                    holdings = ast.literal_eval(holdings_json_or_dict)
                except Exception:
                    holdings = {}

    if save_holdings and holdings:
        try:
            h_file = base_dir / "data" / "portfolio_holdings.json"
            h_file.write_text(json.dumps(holdings, indent=2), encoding="utf-8")
        except Exception:
            pass

    latest_date = get_latest_date()
    orders_df = pm.generate_rebalance_orders(
        cash=capital,
        capital=None,
        top_n=top_n,
        sizing_mode=sizing_mode,
        current_holdings=holdings if holdings else None,
    )

    detail_rows = orders_df[orders_df['action'] != 'SUMMARY'].copy()
    summary_rows = orders_df[orders_df['action'] == 'SUMMARY']

    # HTML Table Styling
    rows_html = ""
    for idx, (_, r) in enumerate(detail_rows.iterrows(), 1):
        act = r['action']
        badge_style = "background-color: #2e7d32; color: white;" if act == 'BUY' else ("background-color: #c62828; color: white;" if act == 'SELL' else "background-color: #f57f17; color: white;")
        price_str = f"₹{r['close_price']:,.2f}" if pd.notnull(r.get('close_price')) else "N/A"
        val_str = f"₹{r['target_value']:,.2f}" if pd.notnull(r.get('target_value')) else "N/A"
        fric_str = f"₹{r['total_friction']:,.2f}" if pd.notnull(r.get('total_friction')) else "N/A"

        rows_html += f"""
        <tr style="border-bottom: 1px solid #444;">
            <td style="padding: 8px; text-align: center;">{idx}</td>
            <td style="padding: 8px; text-align: center;"><span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; {badge_style}">{act}</span></td>
            <td style="padding: 8px; font-weight: bold;">{r['symbol']}</td>
            <td style="padding: 8px;">{r.get('sector', 'OTHER')}</td>
            <td style="padding: 8px; text-align: right;">{price_str}</td>
            <td style="padding: 8px; text-align: right; font-weight: bold;">{int(r['target_shares'])}</td>
            <td style="padding: 8px; text-align: right;">{val_str}</td>
            <td style="padding: 8px; text-align: right; color: #ff8a80;">{fric_str}</td>
            <td style="padding: 8px; font-size: 0.85em; color: #bbb;">{r.get('reason', '')}</td>
        </tr>
        """

    total_cost_str = "N/A"
    total_val_str = "N/A"
    total_fric_str = "N/A"
    if not summary_rows.empty:
        s = summary_rows.iloc[0]
        total_cost_str = f"₹{s.get('total_cost', 0.0):,.2f}"
        total_val_str = f"₹{s.get('target_value', 0.0):,.2f}"
        total_fric_str = f"₹{s.get('total_friction', 0.0):,.2f}"

    html_out = f"""
    <div style="background-color: #1e1e24; color: #fff; padding: 20px; border-radius: 8px; font-family: monospace; margin: 15px 0;">
        <h3 style="color: #64b5f6; margin-top: 0;">💰 Portfolio Rebalance Ledger (As-Of: {latest_date})</h3>
        <p style="color: #aaa; margin-bottom: 15px;">Target Capital: <b>₹{capital:,.0f}</b> | Sizing: <b>{sizing_mode}</b> | Portfolio Size: <b>Top {top_n}</b></p>
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 0.9em;">
                <thead>
                    <tr style="background-color: #2b2b36; color: #90caf9; text-align: left;">
                        <th style="padding: 10px; text-align: center;">#</th>
                        <th style="padding: 10px; text-align: center;">Action</th>
                        <th style="padding: 10px;">Symbol</th>
                        <th style="padding: 10px;">Sector</th>
                        <th style="padding: 10px; text-align: right;">Price</th>
                        <th style="padding: 10px; text-align: right;">Shares</th>
                        <th style="padding: 10px; text-align: right;">Target Value</th>
                        <th style="padding: 10px; text-align: right;">Frictions</th>
                        <th style="padding: 10px;">Execution Reason</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div style="margin-top: 15px; padding: 12px; background-color: #2b2b36; border-radius: 6px; display: flex; justify-content: space-between;">
            <span>Total Target Value: <b>{total_val_str}</b></span>
            <span>Total Statutory Frictions: <b style="color: #ff8a80;">{total_fric_str}</b></span>
            <span>Net Required Capital: <b style="color: #81c784;">{total_cost_str}</b></span>
        </div>
    </div>
    """

    display(HTML(html_out))
    return orders_df


def run_market_diagnostics_view() -> Dict[str, Any]:
    """Computes and renders Market Breadth and Sector Rotation diagnostics."""
    base_dir = Path("/content/Project_MIP_Colab") if Path("/content/Project_MIP_Colab").exists() else get_base_dir()
    latest_date = get_latest_date()

    b_engine = MarketBreadthEngine(base_dir)
    breadth = b_engine.compute_breadth(as_of_date=latest_date)

    s_engine = SectorRotationEngine(base_dir)
    sectors = s_engine.compute_sector_rotation(as_of_date=latest_date)

    reg_raw = breadth.get('regime', {})
    reg_label = reg_raw.get('label', 'Unknown') if isinstance(reg_raw, dict) else str(reg_raw)
    reg_emoji = reg_raw.get('emoji', '⚪') if isinstance(reg_raw, dict) else '⚪'

    ema_part = breadth.get('ema_participation', {})
    pct_200 = ema_part.get('pct_above_200_ema', 0.0)
    pct_50 = ema_part.get('pct_above_50_ema', 0.0)
    pct_20 = ema_part.get('pct_above_20_ema', 0.0)

    html_out = f"""
    <div style="background-color: #1e1e24; color: #fff; padding: 20px; border-radius: 8px; font-family: sans-serif; margin: 15px 0;">
        <h3 style="color: #4fc3f7; margin-top: 0;">📊 Market Breadth & Sector Diagnostics ({latest_date})</h3>
        <div style="display: flex; gap: 20px; margin-bottom: 15px;">
            <div style="flex: 1; background-color: #2b2b36; padding: 12px; border-radius: 6px;">
                <div style="color: #aaa; font-size: 0.85em;">Market Regime</div>
                <div style="font-size: 1.3em; font-weight: bold; margin-top: 5px;">{reg_emoji} {reg_label}</div>
            </div>
            <div style="flex: 1; background-color: #2b2b36; padding: 12px; border-radius: 6px;">
                <div style="color: #aaa; font-size: 0.85em;">Breadth % > 200 EMA</div>
                <div style="font-size: 1.3em; font-weight: bold; margin-top: 5px; color: {'#81c784' if pct_200 >= 50 else '#ef5350'};">{pct_200:.1f}%</div>
            </div>
            <div style="flex: 1; background-color: #2b2b36; padding: 12px; border-radius: 6px;">
                <div style="color: #aaa; font-size: 0.85em;">Breadth % > 50 EMA</div>
                <div style="font-size: 1.3em; font-weight: bold; margin-top: 5px;">{pct_50:.1f}%</div>
            </div>
            <div style="flex: 1; background-color: #2b2b36; padding: 12px; border-radius: 6px;">
                <div style="color: #aaa; font-size: 0.85em;">Breadth % > 20 EMA</div>
                <div style="font-size: 1.3em; font-weight: bold; margin-top: 5px;">{pct_20:.1f}%</div>
            </div>
        </div>
    </div>
    """
    display(HTML(html_out))
    return {"breadth": breadth, "sectors": sectors}
