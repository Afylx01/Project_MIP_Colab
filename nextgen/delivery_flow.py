"""
delivery_flow.py - Feature 4: Alternative Microstructure Data: Delivery Absorption Flow (DAF)
& Smart-Money Footprint Index (SMFI).
References:
- Chordia, T., Roll, R., & Subrahmanyam, A. (2002). Order Imbalance, Liquidity, and Market Returns.
- Acharya, V. V., & Pedersen, L. H. (2005). Asset Pricing with Liquidity Risk.
- National Stock Exchange of India (NSE) Institutional Bhavcopy Microstructure.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Union
import math
import numpy as np
import pandas as pd


@dataclass
class DeliveryFlowConfig:
    rolling_window_days: int = 30
    decay_factor: float = 0.80
    distribution_veto_threshold: float = -1.50
    accumulation_threshold: float = 2.50


def compute_close_location_value(close: float, high: float, low: float) -> float:
    """
    Computes intra-bar Close Location Value (CLV):
    CLV = (2 * Close - High - Low) / (High - Low)
    Returns float in [-1.0, +1.0]. If High == Low, returns 0.0.
    """
    if not (math.isfinite(close) and math.isfinite(high) and math.isfinite(low)):
        return 0.0
    span = high - low
    if span <= 1e-6:
        return 0.0
    clv = (2.0 * close - high - low) / span
    return float(np.clip(clv, -1.0, 1.0))


def compute_delivery_absorption_flow(
    delivery_qty: float,
    close: float,
    high: float,
    low: float,
    median_delivery_val_cr: float = 10.0,
) -> float:
    """
    Computes Session Delivery Absorption Flow (DAF):
    DAF = (Delivery Value / 30d Median Delivery Value) * CLV
    """
    clv = compute_close_location_value(close, high, low)
    deliv_val_cr = (delivery_qty * close) / 1e7
    baseline = max(median_delivery_val_cr, 0.50)  # Floor at ₹50 Lakhs baseline
    multiple = deliv_val_cr / baseline
    daf = multiple * clv
    return float(daf)


def compute_smart_money_footprint_index(
    daf_history: List[float],
    decay_factor: float = 0.80,
) -> float:
    """
    Computes multi-session Smart-Money Footprint Index (SMFI-5):
    SMFI = sum_{k=0}^{K-1} (decay_factor^k * DAF_{current - k})
    """
    if not daf_history:
        return 0.0

    # Most recent entry is at the end of the list
    rev_history = list(reversed(daf_history[-5:]))
    smfi = 0.0
    weight = 1.0
    for val in rev_history:
        smfi += (val * weight)
        weight *= decay_factor
    return float(smfi)


def evaluate_microstructure_buy_gate(
    smfi_score: float,
    distribution_threshold: float = -1.50,
    accumulation_threshold: float = 2.50,
) -> Dict[str, Union[bool, str, float]]:
    """
    Evaluates institutional buy gate based on SMFI score:
    - If SMFI is NaN/non-finite -> BUY VETOED (Fail-Closed Invariant)
    - If SMFI <= distribution_threshold (-1.50) -> BUY VETOED
    - If SMFI >= accumulation_threshold (+2.50) -> ACCUMULATION CONFIRMED
    - Otherwise -> NEUTRAL
    """
    if not math.isfinite(smfi_score):
        return {
            "allow_buy": False,
            "action": "MISSING_DATA_VETO",
            "smfi_score": 0.0,
            "reason": "Delivery microstructure data unavailable or non-finite (Fail-Closed)",
        }

    if smfi_score <= distribution_threshold:
        return {
            "allow_buy": False,
            "action": "INSTITUTIONAL_DISTRIBUTION_VETO",
            "smfi_score": smfi_score,
            "reason": f"Heavy institutional distribution detected (SMFI {smfi_score:.2f} <= {distribution_threshold:.2f})",
        }
    elif smfi_score >= accumulation_threshold:
        return {
            "allow_buy": True,
            "action": "INSTITUTIONAL_ACCUMULATION_CONFIRMED",
            "smfi_score": smfi_score,
            "reason": f"Sustained institutional absorption confirmed (SMFI {smfi_score:.2f} >= {accumulation_threshold:.2f})",
        }
    else:
        return {
            "allow_buy": True,
            "action": "NEUTRAL",
            "smfi_score": smfi_score,
            "reason": "Normal microstructure delivery flow",
        }
