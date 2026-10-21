"""
nextgen/composite_alpha.py - Institutional Composite Alpha Score (CAS) Engine
Blends Total Price Momentum, Idiosyncratic Residual Momentum, and Delivery Flow.
References:
- Blitz, D., Huij, J., & Martens, M. (2011). Residual Momentum. Journal of Empirical Finance.
- Chordia, T., Roll, R., & Subrahmanyam, A. (2002). Order Imbalance and Liquidity.
- Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019). Quality Minus Junk.
"""

from typing import Dict, Optional
import math
import numpy as np
import pandas as pd


DEFAULT_ALPHA_WEIGHTS: Dict[str, float] = {
    "total_momentum": 0.45,
    "residual_momentum": 0.35,
    "delivery_flow": 0.20,
}


def compute_robust_mad_zscore(series: pd.Series, clip_val: float = 3.0) -> pd.Series:
    """
    Computes outlier-resistant cross-sectional z-score using Median Absolute Deviation (MAD):
      Z_rob = clip((X - median(X)) / (1.4826 * MAD(X)), -clip_val, +clip_val)
    Guarantees that micro-cap volume or return spikes do not distort cross-sectional rankings.
    """
    if series.empty or len(series.dropna()) <= 1:
        return pd.Series(0.0, index=series.index)

    clean_s = pd.to_numeric(series, errors="coerce")
    med = clean_s.median()
    if pd.isna(med):
        return pd.Series(0.0, index=series.index)

    mad = (clean_s - med).abs().median()
    scale = 1.4826 * mad

    if scale > 1e-8 and math.isfinite(scale):
        z = (clean_s - med) / scale
    else:
        # Fallback to standard deviation if MAD is zero (e.g. discrete cluster)
        std = clean_s.std()
        if std is not None and math.isfinite(std) and std > 1e-8:
            z = (clean_s - clean_s.mean()) / std
        else:
            z = pd.Series(0.0, index=series.index)

    z_clipped = z.clip(-abs(clip_val), abs(clip_val)).fillna(0.0)
    return z_clipped


def compute_composite_alpha_score(
    df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Synthesizes multiple orthogonal alpha dimensions into a single Composite Alpha Score (CAS):
      CAS_i = w_tot * Z_rob(M_i^tot) + w_res * Z_rob(M_i^res) + w_del * Z_rob(DF_i)
    Automatically re-normalizes weights if any factor is unpopulated or missing.
    """
    if df.empty:
        return df.copy()

    eff_weights = dict(DEFAULT_ALPHA_WEIGHTS)
    if weights:
        eff_weights.update(weights)

    out_df = df.copy()

    # 1. Total Price Momentum Factor
    if "volar_score" in out_df.columns:
        z_tot = compute_robust_mad_zscore(out_df["volar_score"])
    elif "ret_1y" in out_df.columns:
        z_tot = compute_robust_mad_zscore(out_df["ret_1y"])
    else:
        z_tot = pd.Series(0.0, index=out_df.index)

    # 2. Idiosyncratic Residual Momentum Factor
    has_res = False
    if "residual_mom_score" in out_df.columns and out_df["residual_mom_score"].notna().any():
        z_res = compute_robust_mad_zscore(out_df["residual_mom_score"])
        has_res = True
    elif "residual_score" in out_df.columns and out_df["residual_score"].notna().any():
        z_res = compute_robust_mad_zscore(out_df["residual_score"])
        has_res = True
    else:
        z_res = pd.Series(0.0, index=out_df.index)

    # 3. Delivery Flow Factor
    has_del = False
    if "deliv_flow_score" in out_df.columns and out_df["deliv_flow_score"].notna().any():
        z_del = compute_robust_mad_zscore(out_df["deliv_flow_score"])
        has_del = True
    elif "smfi_score" in out_df.columns and out_df["smfi_score"].notna().any():
        z_del = compute_robust_mad_zscore(out_df["smfi_score"])
        has_del = True
    elif "deliv_times" in out_df.columns and out_df["deliv_times"].notna().any():
        z_del = compute_robust_mad_zscore(out_df["deliv_times"])
        has_del = True
    else:
        z_del = pd.Series(0.0, index=out_df.index)

    # Dynamic Weight Normalization
    w_tot = eff_weights.get("total_momentum", 0.45)
    w_res = eff_weights.get("residual_momentum", 0.35) if has_res else 0.0
    w_del = eff_weights.get("delivery_flow", 0.20) if has_del else 0.0

    total_w = w_tot + w_res + w_del
    if total_w > 1e-8:
        w_tot /= total_w
        w_res /= total_w
        w_del /= total_w
    else:
        w_tot = 1.0
        w_res = 0.0
        w_del = 0.0

    cas = (w_tot * z_tot) + (w_res * z_res) + (w_del * z_del)
    out_df["composite_alpha_score"] = cas.round(4)

    # Assign cross-sectional rank (Rank 1 = Highest CAS)
    out_df["composite_rank"] = out_df["composite_alpha_score"].rank(ascending=False, method="min").astype(int)

    return out_df
