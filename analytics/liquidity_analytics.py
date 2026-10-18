"""
analytics/liquidity_analytics.py - Microstructure Liquidity Profiling & Capacity Modeler
Project MIP Institutional Edition (Two Sigma / Man Group AHL / BlackRock Aladdin Standard)

Evaluates portfolio execution liquidity, Days to Liquidate (DL), ADV-30 participation rates,
Aladdin liquidity classification tiers, and Almgren-Chriss strategy capital capacity limits.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


def compute_liquidity_profile(
    orders_df: pd.DataFrame,
    bars_df: Optional[pd.DataFrame] = None,
    capital_inr: float = 1_000_000.0,
    participation_cap: float = 0.10,
    target_impact_bps: float = 50.0,
) -> Dict[str, Any]:
    """
    Computes comprehensive institutional liquidity metrics for active target orders.

    Parameters:
    -----------
    orders_df : DataFrame containing target candidates/orders with columns:
                ['symbol', 'close', 'target_qty', 'target_val']
                Optionally with 'delivery_qty', 'vol_252', etc.
    bars_df : Optional historical price/volume bars dataframe to calculate exact ADV-30.
    capital_inr : Portfolio total capital.
    participation_cap : Conservative daily volume participation limit (default 10%).
    target_impact_bps : Maximum acceptable slippage/market impact drag (default 50 bps).

    Returns:
    --------
    Dict containing detailed liquidity metrics and candidate breakdown table.
    """
    if orders_df is None or orders_df.empty:
        return {
            "portfolio_days_to_liquidate": 0.0,
            "weighted_adv_participation_pct": 0.0,
            "liquidity_bucket_distribution": {},
            "strategy_capacity_crores": 0.0,
            "detailed_table": pd.DataFrame(),
        }

    df = orders_df.copy()

    # If target_qty or target_val not in df, synthesize from standard ATR/equal weight
    if "target_qty" not in df.columns:
        if "close" in df.columns:
            alloc_per_stock = capital_inr / max(len(df), 1)
            df["target_qty"] = (alloc_per_stock / df["close"]).astype(int)
            df["target_val"] = df["target_qty"] * df["close"]
        else:
            df["target_qty"] = 0
            df["target_val"] = 0.0

    # Calculate or estimate ADV-30 and ADTV-30
    adv_list: List[float] = []
    adtv_cr_list: List[float] = []

    if bars_df is not None and not bars_df.empty and "volume" in bars_df.columns:
        for sym in df["symbol"]:
            sym_bars = bars_df[bars_df["symbol"] == sym]
            if len(sym_bars) >= 5:
                recent_vols = sym_bars["volume"].tail(30)
                recent_closes = sym_bars["close"].tail(30)
                adv = float(recent_vols.mean())
                adtv_cr = float((recent_vols * recent_closes).mean() / 1e7)
            else:
                adv = 100_000.0
                adtv_cr = 5.0
            adv_list.append(max(adv, 1.0))
            adtv_cr_list.append(max(adtv_cr, 0.01))
    else:
        # Fallback estimation if bars_df not provided
        for _, row in df.iterrows():
            # If delivery_qty exists in row
            deliv_q = float(row.get("delivery_qty", 0.0) or 0.0)
            px = float(row.get("close", 100.0) or 100.0)
            if deliv_q > 0:
                est_adv = deliv_q * 2.5  # Typical delivery % is 40%, so total vol ~ 2.5x delivery
            else:
                est_adv = 150_000.0  # Conservative institutional liquidity floor
            adv_list.append(est_adv)
            adtv_cr_list.append((est_adv * px) / 1e7)

    df["adv_30"] = adv_list
    df["adtv_30_cr"] = [round(x, 2) for x in adtv_cr_list]

    # 1. Order ADV Participation Rate (%)
    # psi_i = (target_qty / adv_30) * 100
    df["adv_participation_pct"] = (df["target_qty"] / np.maximum(df["adv_30"], 1.0)) * 100.0
    df["adv_participation_pct"] = df["adv_participation_pct"].round(3)

    # 2. Days to Liquidate (DL) under 10% participation cap
    df["days_to_liquidate"] = df["target_qty"] / np.maximum(participation_cap * df["adv_30"], 1.0)
    df["days_to_liquidate"] = df["days_to_liquidate"].round(2)

    # 3. Aladdin Liquidity Classification Tier
    # Tier 1: DL <= 1.0, Tier 2: 1.0 < DL <= 3.0, Tier 3: 3.0 < DL <= 5.0, Tier 4: DL > 5.0
    tiers: List[str] = []
    for dl in df["days_to_liquidate"]:
        if dl <= 1.0:
            tiers.append("TIER-1 (Highly Liquid: <= 1d)")
        elif dl <= 3.0:
            tiers.append("TIER-2 (Liquid: 1-3d)")
        elif dl <= 5.0:
            tiers.append("TIER-3 (Moderate: 3-5d)")
        else:
            tiers.append("TIER-4 (Illiquid: > 5d)")
    df["liquidity_tier"] = tiers

    # Summary metrics
    port_dl = float(df["days_to_liquidate"].max()) if not df.empty else 0.0
    total_val = float(df["target_val"].sum()) if not df.empty else 1.0
    weighted_part = (
        float(np.sum(df["adv_participation_pct"] * df["target_val"]) / max(total_val, 1.0))
        if total_val > 0
        else 0.0
    )

    # Tier counts
    tier_counts = {str(k): int(v) for k, v in df["liquidity_tier"].value_counts().items()}

    # 4. Strategy Capital Capacity Estimation (Almgren-Chriss square-root impact)
    # Capacity = sum_i [ (drag / (eta * sigma_i))^2 * ADTV_i ]
    eta = 0.15  # Institutional market impact parameter for emerging markets
    drag = target_impact_bps / 10000.0  # 0.0050 for 50 bps
    capacity_cr = 0.0
    for i, row in df.iterrows():
        vol = float(row.get("vol_252", 0.35) or 0.35)
        adtv = float(row["adtv_30_cr"])
        scaling_term = (drag / max(eta * vol, 1e-4)) ** 2
        capacity_cr += scaling_term * adtv

    # Apply portfolio concentration divisor (e.g. 20 stocks)
    strategy_capacity_crores = round(capacity_cr * len(df) * 1.5, 2)

    return {
        "portfolio_days_to_liquidate": round(port_dl, 2),
        "weighted_adv_participation_pct": round(weighted_part, 3),
        "liquidity_bucket_distribution": tier_counts,
        "strategy_capacity_crores": strategy_capacity_crores,
        "detailed_table": df,
    }
