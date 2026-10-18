"""
analytics/factor_attribution.py - Brinson-Fachler Sector & Selection Attribution Engine
Project MIP Institutional Edition (FactSet Portfolio Analytics & Bloomberg PORT Standard)

Decomposes portfolio excess returns relative to a reference benchmark into:
1. Sector Allocation Effect (A_j): Value added by sector overweight/underweight decisions.
2. Stock Selection Effect (S_j): Value added by picking outperforming stocks within each sector.
3. Interaction Effect (I_j): Synergy between sector allocation and stock selection.
With Menchero (2000) multi-period logarithmic linking.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd


class BrinsonFachlerEngine:
    """
    Institutional Brinson-Fachler factor and sector attribution engine.
    """

    @staticmethod
    def compute_single_period(
        portfolio_weights: Dict[str, float],
        portfolio_returns: Dict[str, float],
        benchmark_weights: Dict[str, float],
        benchmark_returns: Dict[str, float],
    ) -> pd.DataFrame:
        """
        Computes Brinson-Fachler single-period attribution across sectors.

        Parameters:
        -----------
        portfolio_weights : Dict of sector -> portfolio weight (sums to 1.0)
        portfolio_returns : Dict of sector -> portfolio sector return
        benchmark_weights : Dict of sector -> benchmark sector weight (sums to 1.0)
        benchmark_returns : Dict of sector -> benchmark sector return

        Returns:
        --------
        pd.DataFrame with columns:
          [Sector, W_port, W_bench, R_port, R_bench, Allocation, Selection, Interaction, Total_Active]
        """
        all_sectors = sorted(set(list(portfolio_weights.keys()) + list(benchmark_weights.keys())))

        # Compute total benchmark return
        total_bm_return = sum(
            benchmark_weights.get(sec, 0.0) * benchmark_returns.get(sec, 0.0)
            for sec in all_sectors
        )

        rows = []
        for sec in all_sectors:
            wp = portfolio_weights.get(sec, 0.0)
            wb = benchmark_weights.get(sec, 0.0)
            # Institutional Zero-Weight Convention:
            # If sector not in benchmark (wb == 0), rb defaults to total benchmark return R_B
            rb = benchmark_returns.get(sec, total_bm_return if wb == 0.0 else 0.0)
            # If sector not in portfolio (wp == 0), rp defaults to benchmark sector return rb
            rp = portfolio_returns.get(sec, rb if wp == 0.0 else 0.0)

            # Brinson-Fachler formulation:
            # Allocation: (wp - wb) * (rb - R_B)
            allocation = (wp - wb) * (rb - total_bm_return)

            # Selection: wb * (rp - rb)
            selection = wb * (rp - rb)

            # Interaction: (wp - wb) * (rp - rb)
            interaction = (wp - wb) * (rp - rb)

            total_active = allocation + selection + interaction

            rows.append({
                "sector": sec,
                "weight_portfolio": round(wp, 4),
                "weight_benchmark": round(wb, 4),
                "return_portfolio": round(rp, 4),
                "return_benchmark": round(rb, 4),
                "allocation_effect": round(allocation, 6),
                "selection_effect": round(selection, 6),
                "interaction_effect": round(interaction, 6),
                "total_active_return": round(total_active, 6),
            })

        df = pd.DataFrame(rows)
        return df

    @staticmethod
    def link_multi_period_menchero(
        period_attributions: List[pd.DataFrame],
        portfolio_total_returns: List[float],
        benchmark_total_returns: List[float],
    ) -> pd.DataFrame:
        """
        Links multiple single-period Brinson-Fachler attribution tables across time
        using Menchero (2000) exact logarithmic coefficients.
        """
        T = len(period_attributions)
        if T == 0:
            return pd.DataFrame()
        if T == 1:
            df0 = period_attributions[0].copy()
            df0["cumulative_allocation"] = df0.get("allocation_effect", 0.0)
            df0["cumulative_selection"] = df0.get("selection_effect", 0.0)
            df0["cumulative_interaction"] = df0.get("interaction_effect", 0.0)
            df0["cumulative_total_active"] = df0.get("total_active_return", 0.0)
            return df0

        # Calculate Menchero k_t factors
        k_factors = []
        for t in range(T):
            rp = portfolio_total_returns[t]
            rb = benchmark_total_returns[t]
            if abs(rp - rb) > 1e-7 and (1.0 + rp > 0) and (1.0 + rb > 0):
                kt = (math.log(1.0 + rp) - math.log(1.0 + rb)) / (rp - rb)
            else:
                kt = 1.0 / (1.0 + rb) if (1.0 + rb > 0) else 1.0
            k_factors.append(kt)

        # Compound cumulative returns
        cum_rp = float(np.prod([max(0.0, 1.0 + r) for r in portfolio_total_returns]) - 1.0)
        cum_rb = float(np.prod([max(0.0, 1.0 + r) for r in benchmark_total_returns]) - 1.0)
        total_active_spread = cum_rp - cum_rb

        if abs(total_active_spread) < 1e-12:
            K_scale = 0.0
        else:
            denom = sum(
                k_factors[t] * (portfolio_total_returns[t] - benchmark_total_returns[t])
                for t in range(T)
            )
            K_scale = (total_active_spread / denom) if abs(denom) > 1e-12 else (1.0 + cum_rb)

        # Aggregate across all sectors
        sector_totals: Dict[str, Dict[str, float]] = {}
        for t, df in enumerate(period_attributions):
            kt_scaled = K_scale * k_factors[t]
            for _, row in df.iterrows():
                sec = row["sector"]
                if sec not in sector_totals:
                    sector_totals[sec] = {
                        "allocation": 0.0,
                        "selection": 0.0,
                        "interaction": 0.0,
                        "total_active": 0.0,
                        "mean_wp": 0.0,
                        "mean_wb": 0.0,
                    }
                sector_totals[sec]["allocation"] += kt_scaled * row["allocation_effect"]
                sector_totals[sec]["selection"] += kt_scaled * row["selection_effect"]
                sector_totals[sec]["interaction"] += kt_scaled * row["interaction_effect"]
                sector_totals[sec]["total_active"] += kt_scaled * row["total_active_return"]
                sector_totals[sec]["mean_wp"] += row["weight_portfolio"] / T
                sector_totals[sec]["mean_wb"] += row["weight_benchmark"] / T

        summary_rows = []
        for sec, data in sorted(sector_totals.items()):
            summary_rows.append({
                "sector": sec,
                "mean_weight_portfolio": round(data["mean_wp"], 4),
                "mean_weight_benchmark": round(data["mean_wb"], 4),
                "cumulative_allocation": round(data["allocation"], 6),
                "cumulative_selection": round(data["selection"], 6),
                "cumulative_interaction": round(data["interaction"], 6),
                "cumulative_total_active": round(data["total_active"], 6),
            })

        return pd.DataFrame(summary_rows)
