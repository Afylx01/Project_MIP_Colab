"""
Project MIP Pydroid 3: Mobile Visualization & Tearsheet Engine
Directive: DIR-PROD-PYDROID3-PORT-01 (Institutional Wall Street 5-Chart Suite)

Generates the complete 5 publication-grade institutional charts:
  01. RRG Sector Rotation Dynamics (6-Session Drift)
  02. Sector Rotation Trajectory Bump Chart (60 Sessions)
  03. Market Regime & Breadth Multi-Panel
  04. Industry Momentum Breadth Score Heatmap (40 Sessions)
  05. Sector Excess Return vs Benchmark Across Multi-Horizon (1M, 3M, 6M)
  Plus: Market Overview 3-Panel Dashboard & Interactive Plotly Tearsheet.
"""

import os
import sys
import json
import shutil
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .data_engine import get_base_dir

# Institutional Theme Palette (Wall Street / Bloomberg Terminal Dark)
THEME = {
    "bg_canvas": "#0B0F19",       # Deep Obsidian Navy
    "bg_card": "#131C2E",         # Midnight Slate
    "border": "#24324D",          # Slate-700
    "text_primary": "#F8FAFC",    # Slate-50
    "text_secondary": "#94A3B8",  # Slate-400
    "text_muted": "#64748B",      # Slate-500
    "green": "#10B981",           # Emerald Green (Bullish/Expansion)
    "green_tint": "#064E3B",
    "green_soft": "#34D399",
    "red": "#F43F5E",             # Coral Rose Red (Bearish/Contraction)
    "red_tint": "#881337",
    "red_soft": "#FB7185",
    "blue": "#38BDF8",            # Electric Sky Blue
    "blue_dark": "#0284C7",
    "amber": "#F59E0B",           # Warm Amber (Warning/Neutral)
    "purple": "#A855F7",          # Bright Violet
    "cyan": "#06B6D4",            # Cyan
    "orange": "#F97316",          # Orange
    "grid": "#24324D",
    "grid_alpha": 0.45,
}

BUMP_PALETTE = [
    "#38BDF8", "#34D399", "#FBBF24", "#F43F5E", "#A78BFA",
    "#FB923C", "#06B6D4", "#E879F9", "#4ADE80", "#94A3B8",
    "#F472B6", "#60A5FA", "#2DD4BF", "#FACC15", "#C084FC"
]


def _clean_slug(universe_label: str) -> str:
    return str(universe_label).strip().replace(" ", "").replace("(", "").replace(")", "").replace("-", "_")


def _apply_ax_styling(ax, title: str, subtitle: Optional[str] = None):
    """Applies institutional slate card styling, grid, and typography to an axis."""
    ax.set_facecolor(THEME["bg_card"])
    for spine in ax.spines.values():
        spine.set_color(THEME["border"])
        spine.set_linewidth(1.0)
    ax.grid(True, linestyle="--", linewidth=0.6, color=THEME["grid"], alpha=THEME["grid_alpha"])
    ax.tick_params(colors=THEME["text_secondary"], labelsize=9)
    if title:
        clean_title = str(title).replace("🟢", "").replace("🔴", "").replace("🟡", "").strip()
        clean_sub = str(subtitle).replace("🟢", "").replace("🔴", "").replace("🟡", "").strip() if subtitle else None
        if clean_sub:
            ax.set_title(f"{clean_title}\n", color=THEME["text_primary"], fontsize=11, fontweight="bold", pad=12, loc="left")
            ax.text(0.0, 1.02, clean_sub, transform=ax.transAxes, color=THEME["text_muted"], fontsize=8.5, va="bottom")
        else:
            ax.set_title(clean_title, color=THEME["text_primary"], fontsize=11, fontweight="bold", pad=10, loc="left")


# ── 1. RRG SNAPSHOT ──
def generate_rrg_snapshot_chart(
    sector_data: Dict,
    ind_hist_df: Optional[pd.DataFrame] = None,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates 01. RRG Sector Rotation Dynamics (6-Session Drift & Quadrants)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "01_rrg_snapshot.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 9), dpi=150)
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])
        ax.set_facecolor(THEME["bg_card"])

        sectors = sector_data.get("sectors", [])
        if not sectors:
            return target_path

        # Extract current coordinates
        all_x = [float(s.get("rrg_rs_ratio", 100.0)) for s in sectors]
        all_y = [float(s.get("rrg_rs_momentum", 100.0)) for s in sectors]

        min_x, max_x = min(min(all_x), 97.0), max(max(all_x), 103.0)
        min_y, max_y = min(min(all_y), 97.0), max(max(all_y), 103.0)
        pad_x = max(1.5, (max_x - min_x) * 0.12)
        pad_y = max(1.5, (max_y - min_y) * 0.12)
        xlim = (min_x - pad_x, max_x + pad_x)
        ylim = (min_y - pad_y, max_y + pad_y)

        # Shaded Quadrants
        ax.fill_between([100.0, xlim[1]], 100.0, ylim[1], color=THEME["green_tint"], alpha=0.35, zorder=0)
        ax.fill_between([xlim[0], 100.0], 100.0, ylim[1], color=THEME["blue_dark"], alpha=0.25, zorder=0)
        ax.fill_between([100.0, xlim[1]], ylim[0], 100.0, color=THEME["amber"], alpha=0.15, zorder=0)
        ax.fill_between([xlim[0], 100.0], ylim[0], 100.0, color=THEME["red_tint"], alpha=0.30, zorder=0)

        # Benchmark Crosshair at (100, 100)
        ax.axvline(100.0, color=THEME["text_muted"], linestyle="--", linewidth=1.2, zorder=1)
        ax.axhline(100.0, color=THEME["text_muted"], linestyle="--", linewidth=1.2, zorder=1)

        # Quadrant Badges
        q_badge_props = dict(boxstyle="round,pad=0.4", facecolor=THEME["bg_card"], edgecolor=THEME["border"], alpha=0.85)
        ax.text(xlim[1] - pad_x * 0.2, ylim[1] - pad_y * 0.2, "LEADING (Bullish)", color=THEME["green"], fontsize=9.5, fontweight="bold", ha="right", va="top", bbox=q_badge_props)
        ax.text(xlim[0] + pad_x * 0.2, ylim[1] - pad_y * 0.2, "IMPROVING (Recovery)", color=THEME["blue"], fontsize=9.5, fontweight="bold", ha="left", va="top", bbox=q_badge_props)
        ax.text(xlim[1] - pad_x * 0.2, ylim[0] + pad_y * 0.2, "WEAKENING (Fading)", color=THEME["amber"], fontsize=9.5, fontweight="bold", ha="right", va="bottom", bbox=q_badge_props)
        ax.text(xlim[0] + pad_x * 0.2, ylim[0] + pad_y * 0.2, "LAGGING (Bearish)", color=THEME["red"], fontsize=9.5, fontweight="bold", ha="left", va="bottom", bbox=q_badge_props)

        # Plot sector points and drift trails
        quad_vectors = {
            "LEADING": (1.1, 0.9), "IMPROVING": (-1.1, 0.9),
            "WEAKENING": (1.1, -0.9), "LAGGING": (-1.1, -0.9),
        }

        for idx, s in enumerate(sectors):
            sec = s["sector"]
            x, y = float(s.get("rrg_rs_ratio", 100.0)), float(s.get("rrg_rs_momentum", 100.0))
            quad = str(s.get("rrg_quadrant", "UNKNOWN")).upper()
            col = THEME["green"] if quad == "LEADING" else (THEME["blue"] if quad == "IMPROVING" else (THEME["amber"] if quad == "WEAKENING" else THEME["red"]))

            # Check for history drift trail
            if ind_hist_df is not None and not ind_hist_df.empty:
                sec_col = "Sector" if "Sector" in ind_hist_df.columns else "industry"
                sub_h = ind_hist_df[ind_hist_df[sec_col] == sec].tail(6)
                if len(sub_h) >= 2 and "RS-Ratio" in sub_h.columns and "RS-Mom %" in sub_h.columns:
                    hx = sub_h["RS-Ratio"].tolist()
                    hy = (sub_h["RS-Mom %"] + 100.0).tolist()
                    ax.plot(hx, hy, color=col, alpha=0.6, linewidth=1.5, zorder=2)
                    for step, (px, py) in enumerate(zip(hx[:-1], hy[:-1])):
                        ax.scatter([px], [py], s=15 + step * 8, color=col, alpha=0.5, zorder=2)

            # Plot current bubble
            ax.scatter([x], [y], s=260, color=col, alpha=0.9, edgecolors=THEME["text_primary"], linewidth=1.4, zorder=4)

            # 2-letter acronym
            words = sec.replace("&", " ").replace("-", " ").split()
            acronym = "".join(w[0] for w in words[:2]).upper() if len(words) >= 2 else sec[:2].upper()
            ax.text(x, y, acronym, color=THEME["text_primary"], fontsize=8, fontweight="bold", ha="center", va="center", zorder=5)

            # Quadrant callout pill
            vx, vy = quad_vectors.get(quad, (1.0, 1.0))
            offset_x = vx * (0.8 + (idx % 3) * 0.4)
            offset_y = vy * (0.6 + (idx % 4) * 0.35)

            clean_name = sec.replace("_", " ").title()[:18]
            pill_text = f"{clean_name}\n({x:.1f}, {y:.1f})"
            ax.annotate(
                pill_text, (x, y),
                xytext=(x + offset_x, y + offset_y),
                color=THEME["text_primary"], fontsize=7.5, fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", facecolor=THEME["bg_card"], edgecolor=col, alpha=0.9, linewidth=1.0),
                arrowprops=dict(arrowstyle="-", color=col, lw=0.8, alpha=0.7),
                ha="center", va="center", zorder=6
            )

        ax.set_xlim(xlim)
        ax.set_ylim(ylim)
        ax.set_xlabel("RS-Ratio (Trend Strength vs Benchmark 100)", color=THEME["text_secondary"], fontsize=10, fontweight="bold", labelpad=8)
        ax.set_ylabel("RS-Momentum (Velocity vs Benchmark 100)", color=THEME["text_secondary"], fontsize=10, fontweight="bold", labelpad=8)
        _apply_ax_styling(ax, f"01. RRG Sector Rotation Dynamics — {universe_label}", "Relative Rotation Graph (RRG) — JdG RS-Ratio vs RS-Momentum with 6-Session Drift")

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


# ── 2. SECTOR ROTATION BUMP CHART ──
def generate_rotation_bump_chart(
    bars_df: Optional[pd.DataFrame],
    target_date: str,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates 02. Sector Rotation Trajectory Bump Chart over last 60 Sessions."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "02_rotation_bump.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 9), dpi=150)
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])
        ax.set_facecolor(THEME["bg_card"])

        if bars_df is None or bars_df.empty:
            _apply_ax_styling(ax, f"02. Sector Trajectory Bump Chart — {universe_label}", "Insufficient historical bars to compute bump chart")
            plt.tight_layout()
            fig.savefig(target_path, dpi=150)
            return target_path

        # Prepare daily ranks
        sub = bars_df.copy()
        sec_col = "sector" if "sector" in sub.columns else ("industry" if "industry" in sub.columns else None)
        if not sec_col:
            return target_path

        all_dates = sorted(sub["date"].unique())
        d_60 = all_dates[-60:]
        sub_60 = sub[sub["date"].isin(d_60)].copy()

        if "above_200" not in sub_60.columns and "ema_200" in sub_60.columns:
            sub_60["above_200"] = sub_60["close"] > sub_60["ema_200"]
        if "above_50" not in sub_60.columns and "ema_50" in sub_60.columns:
            sub_60["above_50"] = sub_60["close"] > sub_60["ema_50"]

        p200_col = "above_200" if "above_200" in sub_60.columns else "close"
        p50_col = "above_50" if "above_50" in sub_60.columns else "close"

        daily = sub_60.groupby(["date", sec_col]).agg(
            p200=(p200_col, lambda s: (s > 0).mean()),
            p50=(p50_col, lambda s: (s > 0).mean())
        ).reset_index()
        daily["score"] = (0.5 * daily["p200"] + 0.5 * daily["p50"]) * 100.0
        daily["rank"] = daily.groupby("date")["score"].rank(ascending=False, method="min")

        bump_pivot = daily.pivot(index="date", columns=sec_col, values="rank").sort_index()
        if bump_pivot.empty or len(bump_pivot) < 2:
            _apply_ax_styling(ax, f"02. Sector Trajectory Bump Chart — {universe_label}", "Insufficient time series depth")
            plt.tight_layout()
            fig.savefig(target_path, dpi=150)
            return target_path

        latest_ranks = bump_pivot.iloc[-1].sort_values()
        top10_inds = latest_ranks.head(10).index.tolist()

        x_vals = range(len(bump_pivot))
        for idx, ind in enumerate(top10_inds):
            col = BUMP_PALETTE[idx % len(BUMP_PALETTE)]
            r_series = bump_pivot[ind].values
            ax.plot(x_vals, r_series, color=col, lw=2.4, alpha=0.9, zorder=3, marker="o", markersize=3.5)

            r_start, r_end = int(r_series[0]), int(r_series[-1])
            delta = r_start - r_end
            d_str = f"+{delta}" if delta > 0 else (f"{delta}" if delta < 0 else "0")

            clean_name = ind.replace("_", " ").title()[:20]
            ax.annotate(f"#{r_end} {clean_name} ({d_str})", (len(bump_pivot) - 1, r_end),
                        xytext=(8, 0), textcoords="offset points", va="center", fontsize=8, fontweight="bold", color=col)
            ax.annotate(f"#{r_start}", (0, r_start),
                        xytext=(-8, 0), textcoords="offset points", ha="right", va="center", fontsize=7.5, color=THEME["text_muted"])

        max_rank = max(11, int(latest_ranks.head(10).max()) + 1)
        ax.set_ylim(max_rank, 0.5)
        ax.set_yticks(range(1, min(max_rank, 12)))
        step = max(1, len(bump_pivot) // 8)
        ax.set_xticks(list(x_vals)[::step])
        ax.set_xticklabels([str(d)[:10] for d in bump_pivot.index[::step]], rotation=35, fontsize=8, color=THEME["text_secondary"])

        ax.set_ylabel("Industry Rank (1 = Top Leadership)", color=THEME["text_secondary"], fontsize=10, fontweight="bold")
        _apply_ax_styling(ax, f"02. Sector Trajectory Bump Chart — {universe_label}", f"Top 10 Ranked Sectors over Last {len(bump_pivot)} Sessions (Rank #1 at Top with Net Rank Δ)")

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


# ── 3. MARKET REGIME & BREADTH MULTI-PANEL ──
def generate_market_breadth_multipanel(
    breadth_hist_df: Optional[pd.DataFrame],
    target_date: str,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates 03. Market Regime & Breadth Multi-Panel Chart."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "03_market_breadth.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 10), dpi=150, sharex=True, gridspec_kw={"height_ratios": [0.42, 0.29, 0.29]})
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])

        if breadth_hist_df is None or breadth_hist_df.empty:
            for ax in (ax1, ax2, ax3): _apply_ax_styling(ax, "", "")
            plt.tight_layout()
            fig.savefig(target_path, dpi=150)
            return target_path

        m = breadth_hist_df.sort_values("Date").tail(60).reset_index(drop=True)
        x = range(len(m))
        dates = [str(d)[:10] for d in m["Date"]]

        # Panel 1: Benchmark Regime
        raw_bm = m["Benchmark Px"] if "Benchmark Px" in m.columns else (m["Close"] if "Close" in m.columns else np.linspace(24000, 25500, len(m)))
        bm_px = pd.Series(raw_bm, index=x)
        sma20 = m["SMA 20"] if "SMA 20" in m.columns else bm_px.rolling(20, min_periods=5).mean().bfill()
        if not isinstance(sma20, pd.Series):
            sma20 = pd.Series(sma20, index=x)

        ax1.plot(x, bm_px, color=THEME["blue"], lw=2.2, label="Benchmark Close")
        ax1.plot(x, sma20, color=THEME["amber"], lw=1.6, linestyle="--", label="20-Day SMA")
        is_bull = float(bm_px.iloc[-1]) >= float(sma20.iloc[-1])
        ax1.fill_between(x, min(bm_px)*0.99, max(bm_px)*1.01, color=THEME["green_tint"] if is_bull else THEME["red_tint"], alpha=0.18)
        ax1.legend(loc="upper left", facecolor=THEME["bg_card"], edgecolor=THEME["border"], labelcolor=THEME["text_primary"], fontsize=8.5)
        _apply_ax_styling(ax1, f"03. Market Regime & Breadth Dynamics — {universe_label}", f"Panel 1: Benchmark Close vs 20-SMA ({'🟢 BULL REGIME' if is_bull else '🔴 BEAR REGIME - CASH ACTIVE'})")

        # Panel 2: Trend Participation %
        p50 = m["% > 50 EMA"] if "% > 50 EMA" in m.columns else pd.Series(50, index=x)
        p200 = m["% > 200 EMA"] if "% > 200 EMA" in m.columns else pd.Series(45, index=x)
        ax2.plot(x, p50, color=THEME["cyan"], lw=1.8, label="% > 50 EMA")
        ax2.plot(x, p200, color=THEME["purple"], lw=1.8, label="% > 200 EMA")
        ax2.axhline(50.0, color=THEME["text_muted"], linestyle=":", lw=1.0)
        ax2.set_ylim(0, 100)
        ax2.set_ylabel("% Participation", color=THEME["text_secondary"], fontsize=9)
        ax2.legend(loc="upper left", facecolor=THEME["bg_card"], edgecolor=THEME["border"], labelcolor=THEME["text_primary"], fontsize=8.5)
        _apply_ax_styling(ax2, "", "Panel 2: Trend Breadth Participation (% > 50 EMA & % > 200 EMA)")

        # Panel 3: Elite % & 52w Highs
        ax3_twin = ax3.twinx()
        elite = m["Elite %"] if "Elite %" in m.columns else pd.Series(10, index=x)
        highs = m["52w Highs"] if "52w Highs" in m.columns else pd.Series(5, index=x)

        ax3.plot(x, elite, color=THEME["green"], lw=2.0, label="Elite Breadth %")
        ax3_twin.bar(x, highs, color=THEME["amber"], alpha=0.5, width=0.6, label="New 52w Highs")
        ax3.set_ylabel("Elite %", color=THEME["green"], fontsize=9)
        ax3_twin.set_ylabel("New 52W Highs", color=THEME["amber"], fontsize=9)
        ax3_twin.tick_params(colors=THEME["amber"], labelsize=8.5)
        _apply_ax_styling(ax3, "", "Panel 3: Elite Breadth % (>200 EMA & Near 52wH) & Daily 52W High Spikes")

        # X-Ticks on bottom panel
        step = max(1, len(m) // 8)
        ax3.set_xticks(list(x)[::step])
        ax3.set_xticklabels(dates[::step], rotation=35, fontsize=8, color=THEME["text_secondary"])

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


# ── 4. INDUSTRY HEATMAP ──
def generate_industry_heatmap(
    bars_df: Optional[pd.DataFrame],
    target_date: str,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates 04. Industry Momentum Breadth Score Heatmap across last 40 Sessions."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "04_industry_heatmap.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 9), dpi=150)
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])
        ax.set_facecolor(THEME["bg_card"])

        if bars_df is None or bars_df.empty:
            _apply_ax_styling(ax, f"04. Industry Momentum Heatmap — {universe_label}", "No bars data available")
            plt.tight_layout()
            fig.savefig(target_path, dpi=150)
            return target_path

        sub = bars_df.copy()
        sec_col = "sector" if "sector" in sub.columns else ("industry" if "industry" in sub.columns else None)
        if not sec_col:
            return target_path

        all_dates = sorted(sub["date"].unique())
        d_40 = all_dates[-40:]
        sub_40 = sub[sub["date"].isin(d_40)]

        p200_col = "above_200" if "above_200" in sub_40.columns else "close"
        p50_col = "above_50" if "above_50" in sub_40.columns else "close"

        daily = sub_40.groupby(["date", sec_col]).agg(
            p200=(p200_col, lambda s: (s > 0).mean()),
            p50=(p50_col, lambda s: (s > 0).mean())
        ).reset_index()
        daily["score"] = (0.5 * daily["p200"] + 0.5 * daily["p50"]) * 100.0

        heat_pivot = daily.pivot(index=sec_col, columns="date", values="score").fillna(50.0)
        if heat_pivot.empty:
            return target_path

        # Sort industries by latest score descending
        latest = heat_pivot.iloc[:, -1].sort_values(ascending=False)
        heat_pivot = heat_pivot.loc[latest.index]

        # Clean row labels (add star to top 5)
        row_labels = []
        for r, ind in enumerate(heat_pivot.index, 1):
            clean = ind.replace("_", " ").title()[:24]
            star = "★ " if r <= 5 else "   "
            row_labels.append(f"{star}#{r:2d} {clean}")

        im = ax.imshow(heat_pivot.values, cmap="RdYlGn", aspect="auto", vmin=15, vmax=85)

        # Colorbar
        cbar = fig.colorbar(im, ax=ax, orientation="vertical", pad=0.02, shrink=0.85)
        cbar.ax.tick_params(colors=THEME["text_secondary"], labelsize=8)
        cbar.set_label("Breadth Score (0-100)", color=THEME["text_secondary"], fontsize=9, fontweight="bold")

        # Axes
        ax.set_yticks(range(len(heat_pivot)))
        ax.set_yticklabels(row_labels, fontsize=8, color=THEME["text_primary"], fontweight="medium")

        step = max(1, len(d_40) // 8)
        ax.set_xticks(range(0, len(d_40), step))
        ax.set_xticklabels([str(d)[5:] for d in heat_pivot.columns[::step]], rotation=35, fontsize=8, color=THEME["text_secondary"])

        _apply_ax_styling(ax, f"04. Industry Breadth Score Heatmap — {universe_label}", "40-Session Industry Breadth Score Heatmap sorted by Current Rank (★ = Top 5 Leaders)")

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


# ── 5. SECTOR EXCESS RETURNS ──
def generate_excess_returns_chart(
    sector_data: Dict,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates 05. Sector Excess Return vs Benchmark Across Multi-Horizon Periods (1M, 3M, 6M)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "05_excess_returns.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(14, 9), dpi=150)
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])
        ax.set_facecolor(THEME["bg_card"])

        sectors = sector_data.get("sectors", [])
        if not sectors:
            return target_path

        # Sort by 3M excess return desc
        sorted_secs = sorted(sectors, key=lambda s: float(s.get("excess_3m", s.get("alpha_3m", 0.0))), reverse=True)[:15]

        y_pos = np.arange(len(sorted_secs))
        bar_height = 0.25

        names = [s["sector"].replace("_", " ").title()[:20] for s in sorted_secs]
        e1m = [float(s.get("excess_1m", s.get("alpha_1m", 0.0))) for s in sorted_secs]
        e3m = [float(s.get("excess_3m", s.get("alpha_3m", 0.0))) for s in sorted_secs]
        e6m = [float(s.get("excess_6m", s.get("alpha_6m", 0.0))) for s in sorted_secs]

        b1 = ax.barh(y_pos - bar_height, e1m, height=bar_height, color=THEME["blue"], alpha=0.85, label="1M Excess %")
        b2 = ax.barh(y_pos, e3m, height=bar_height, color=THEME["green"], alpha=0.85, label="3M Excess %")
        b3 = ax.barh(y_pos + bar_height, e6m, height=bar_height, color=THEME["amber"], alpha=0.85, label="6M Excess %")

        ax.axvline(0, color=THEME["text_muted"], linestyle="--", linewidth=1.0)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=8.5, color=THEME["text_primary"], fontweight="medium")
        ax.invert_yaxis()  # Highest at top

        ax.set_xlabel("Relative Strength Alpha vs Benchmark (%)", color=THEME["text_secondary"], fontsize=9.5, fontweight="bold")
        ax.legend(loc="lower right", facecolor=THEME["bg_card"], edgecolor=THEME["border"], labelcolor=THEME["text_primary"], fontsize=8.5)

        # Bar end callouts
        for idx, (v1, v3) in enumerate(zip(e1m, e3m)):
            offset = 0.4 if v3 >= 0 else -0.4
            ha = "left" if v3 >= 0 else "right"
            ax.text(v3 + offset, idx, f"{v3:+.1f}%", va="center", ha=ha, fontsize=7.5, color=THEME["green_soft"] if v3 >= 0 else THEME["red_soft"], fontweight="bold")

        _apply_ax_styling(ax, f"05. Sector Excess Return vs Benchmark Across Multi-Horizon Periods — {universe_label}", "Relative Alpha Across 1-Month, 3-Month, and 6-Month Windows (Sorted by 3M Alpha)")

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


# ── MASTER OVERVIEW DASHBOARD ──
def generate_matplotlib_dashboard(
    breadth_data: Dict,
    sector_data: Dict,
    top_df: pd.DataFrame,
    output_png: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates the executive 3-panel quick-look dashboard."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path = output_png or (get_base_dir() / "reports" / "charts" / "market_overview_chart.png")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(19, 6.2), dpi=150)
    try:
        fig.patch.set_facecolor(THEME["bg_canvas"])

        # Panel 1: Breadth
        pct_200 = float(breadth_data.get("pct_above_200_ema", 50.0))
        pct_50 = float(breadth_data.get("pct_above_50_ema", 50.0))
        pct_20 = float(breadth_data.get("pct_above_20_ema", 50.0))
        near_52w = float(breadth_data.get("pct_within_20pct_52wh", 50.0))
        net_highs = int(breadth_data.get("net_52w_highs", 0))

        b_labels = ["Trend (>200 EMA)", "Momentum (>50 EMA)", "Short-Term (>20 EMA)", "Proximity (Near 52wH)"]
        b_vals = [pct_200, pct_50, pct_20, near_52w]
        b_colors = [THEME["green"] if v >= 50 else THEME["red"] for v in b_vals]

        y_pos = range(len(b_labels))
        ax1.barh(y_pos, b_vals, color=b_colors, height=0.45, alpha=0.9)
        ax1.set_xlim(0, 100)
        ax1.set_yticks(y_pos)
        ax1.set_yticklabels(b_labels, fontsize=8.5, color=THEME["text_primary"], fontweight="medium")
        ax1.axvline(50, color=THEME["text_muted"], linestyle="--", linewidth=1.0)
        for i, v in enumerate(b_vals):
            ax1.text(v + 1.5, i, f"{v:.1f}%", va="center", fontsize=8.5, color=THEME["text_primary"], fontweight="bold")
        _apply_ax_styling(ax1, "Market Breadth & Participation", f"Net 52w Highs: {net_highs:+d} | Target Universe: {universe_label}")

        # Panel 2: Sector Alpha
        sectors = sector_data.get("sectors", [])[:10]
        if sectors:
            s_names = [s["sector"].replace("_", " ").title()[:15] for s in sectors]
            s_alpha = [float(s.get("alpha_1m", 0.0)) for s in sectors]
            s_colors = [THEME["green"] if a >= 0 else THEME["red"] for a in s_alpha]
            sy_pos = range(len(s_names))
            ax2.barh(sy_pos, s_alpha, color=s_colors, height=0.5, alpha=0.9)
            ax2.set_yticks(sy_pos)
            ax2.set_yticklabels(s_names, fontsize=8, color=THEME["text_primary"])
            ax2.axvline(0, color=THEME["text_muted"], linestyle="--", linewidth=1.0)
            ax2.invert_yaxis()
            for i, a in enumerate(s_alpha):
                offset = 0.2 if a >= 0 else -0.2
                ha = "left" if a >= 0 else "right"
                ax2.text(a + offset, i, f"{a:+.1f}%", va="center", ha=ha, fontsize=7.5, color=THEME["text_primary"], fontweight="bold")
        _apply_ax_styling(ax2, "Top Sector Alpha (1-Month)", "Equal-Weighted Relative Alpha vs NIFTY 500")

        # Panel 3: Candidates RRG Scatter
        if top_df is not None and not top_df.empty:
            c_x = top_df.get("rrg_rs_ratio", pd.Series(100, index=top_df.index))
            c_y = top_df.get("rrg_rs_momentum", pd.Series(100, index=top_df.index))
            ax3.scatter(c_x, c_y, color=THEME["blue"], s=100, edgecolors=THEME["text_primary"], linewidth=1.0, alpha=0.85)
            ax3.axvline(100, color=THEME["text_muted"], linestyle="--", linewidth=1.0)
            ax3.axhline(100, color=THEME["text_muted"], linestyle="--", linewidth=1.0)
            for _, r in top_df.head(10).iterrows():
                ax3.annotate(str(r["symbol"]), (r.get("rrg_rs_ratio", 100), r.get("rrg_rs_momentum", 100)),
                             fontsize=7.5, color=THEME["text_primary"], xytext=(3, 3), textcoords="offset points")
        _apply_ax_styling(ax3, "Top Candidates Momentum (RRG)", "Top 20 Volar Momentum Candidates Scatter")

        plt.tight_layout()
        fig.savefig(target_path, dpi=150, facecolor=THEME["bg_canvas"], edgecolor="none")
        return target_path
    finally:
        plt.close(fig)


def generate_plotly_tearsheet(
    breadth_data: Dict,
    sector_data: Dict,
    top_df: pd.DataFrame,
    output_html: Optional[Path] = None,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates a mobile-friendly interactive Plotly HTML tearsheet."""
    base_dir = get_base_dir()
    reports_dir = base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_html or (reports_dir / "mip_mobile_tearsheet.html")

    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots

        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=(
                "Market Breadth Participation (%)",
                "Sector Alpha 1M vs Benchmark",
                "Top Momentum Candidates RRG Scatter",
                "Sector Internal Breadth (% > 200 EMA)"
            ),
            vertical_spacing=0.15,
            horizontal_spacing=0.12
        )

        # 1. Breadth Bar Chart
        tp = breadth_data.get("trend_participation", {})
        hp = breadth_data.get("high_proximity", {})
        b_labels = ["% > 200 EMA", "% > 50 EMA", "% > 20 EMA", "% Near 52wH"]
        b_vals = [
            tp.get("pct_above_200_ema", 0),
            tp.get("pct_above_50_ema", 0),
            tp.get("pct_above_20_ema", 0),
            hp.get("pct_within_20pct_52wh", 0)
        ]
        fig.add_trace(
            go.Bar(
                x=b_labels, y=b_vals,
                marker_color=[THEME["green"] if v >= 50 else THEME["red"] for v in b_vals],
                name="Breadth %"
            ),
            row=1, col=1
        )

        # 2. Sector Alpha Bar Chart
        sectors = sector_data.get("sectors", [])
        sec_names = [s["sector"] for s in sectors]
        sec_alphas = [s.get("alpha_1m", 0.0) for s in sectors]
        fig.add_trace(
            go.Bar(
                x=sec_names, y=sec_alphas,
                marker_color=[THEME["green"] if a >= 0 else THEME["red"] for a in sec_alphas],
                name="Sector Alpha 1M"
            ),
            row=1, col=2
        )

        # 3. RRG Scatter
        if not top_df.empty and "rrg_rs_ratio" in top_df.columns:
            fig.add_trace(
                go.Scatter(
                    x=top_df["rrg_rs_ratio"],
                    y=top_df["rrg_rs_momentum"],
                    mode="markers+text",
                    text=top_df["symbol"],
                    textposition="top center",
                    marker=dict(size=11, color=THEME["blue"], line=dict(color="#FFFFFF", width=1.2)),
                    name="Top Candidates"
                ),
                row=2, col=1
            )

        # 4. Sector Breadth Bar Chart
        sec_breadths = [s.get("breadth_200_pct", 0.0) for s in sectors]
        fig.add_trace(
            go.Bar(
                x=sec_names, y=sec_breadths,
                marker_color=THEME["purple"],
                name="Sector % > 200 EMA"
            ),
            row=2, col=2
        )

        fig.update_layout(
            paper_bgcolor=THEME["bg_canvas"],
            plot_bgcolor=THEME["bg_card"],
            font=dict(color=THEME["text_primary"], family="sans-serif"),
            title=f"Project MIP - Mobile Quantitative Tearsheet ({breadth_data.get('as_of_date', 'LIVE')}) [{universe_label}]",
            height=850,
            showlegend=False
        )

        fig.write_html(str(out_path))
        return out_path

    except ImportError:
        return generate_pure_html_fallback(breadth_data, sector_data, top_df, out_path, universe_label)


def generate_pure_html_fallback(
    breadth_data: Dict,
    sector_data: Dict,
    top_df: pd.DataFrame,
    out_path: Path,
    universe_label: str = "NIFTY 500",
) -> Path:
    """Generates a standalone styled HTML report with zero external dependencies."""
    as_of = breadth_data.get("as_of_date", "LIVE")
    regime = breadth_data.get("regime", {})
    tp = breadth_data.get("trend_participation", {})

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Project MIP Mobile Tearsheet - {as_of} [{universe_label}]</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b0f19; color: #f8fafc; margin: 15px; }}
h1 {{ color: #38bdf8; font-size: 20px; }}
.card {{ background: #131c2e; border: 1px solid #24324d; border-radius: 8px; padding: 15px; margin-bottom: 15px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ padding: 8px; text-align: left; border-bottom: 1px solid #24324d; }}
th {{ background: #1e293b; color: #94a3b8; }}
.green {{ color: #10b981; font-weight: bold; }}
.red {{ color: #f43f5e; font-weight: bold; }}
</style>
</head>
<body>
<h1>🚀 Project MIP: Mobile Quantitative Tearsheet</h1>
<p>As of Date: <b>{as_of}</b> | Universe: <b>{universe_label}</b> | Regime: <b>{regime.get('label', 'N/A')}</b></p>

<div class="card">
  <h3>Market Breadth Summary</h3>
  <p>% > 200 EMA: <b>{tp.get('pct_above_200_ema', 0)}%</b> | % > 50 EMA: <b>{tp.get('pct_above_50_ema', 0)}%</b> | % > 20 EMA: <b>{tp.get('pct_above_20_ema', 0)}%</b></p>
</div>

<div class="card">
  <h3>Top Momentum Candidates (Ranked Strictly by Volar)</h3>
  <table>
    <tr><th>Rank</th><th>Symbol</th><th>Close</th><th>Sector</th><th>Volar</th><th>RRG</th></tr>
"""
    for _, r in top_df.head(20).iterrows():
        html += f"<tr><td>{int(r.get('rank', 0))}</td><td><b>{r['symbol']}</b></td><td>₹{r['close']:.2f}</td><td>{r.get('sector','')}</td><td>{r.get('volar_score',0):.2f}</td><td>{r.get('rrg_quadrant','')}</td></tr>\n"

    html += """
  </table>
</div>
</body>
</html>
"""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path


# ── ORCHESTRATOR ──
def generate_all_visuals(
    as_of_date: str,
    breadth_data: Dict,
    sector_data: Dict,
    top_df: pd.DataFrame,
    ind_hist_df: Optional[pd.DataFrame] = None,
    breadth_hist_df: Optional[pd.DataFrame] = None,
    universe_label: str = "NIFTY 500",
    bars_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Path]:
    """
    Orchestrates creation of all 5 institutional visual momentum charts + overview:
      01. RRG Snapshot (PNG)
      02. Sector Rotation Bump Chart (PNG)
      03. Market Breadth Multi-Panel (PNG)
      04. Industry Breadth Heatmap (PNG)
      05. Sector Excess Returns (PNG)
      Plus: Market Overview Dashboard (PNG) & HTML Tearsheet.
    """
    base_dir = get_base_dir()
    reports_dir = base_dir / "reports"
    charts_dir = reports_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    deliv_dir = reports_dir / "deliverables"
    deliv_dir.mkdir(parents=True, exist_ok=True)
    android_deliv = base_dir / "reports" / "deliverables"
    try:
        android_deliv.mkdir(parents=True, exist_ok=True)
    except Exception:
        android_deliv = None

    slug = _clean_slug(universe_label)

    # 5 Dedicated Institutional Chart Paths
    p1_path = charts_dir / f"01_rrg_snapshot_{as_of_date}_{slug}.png"
    p2_path = charts_dir / f"02_rotation_bump_{as_of_date}_{slug}.png"
    p3_path = charts_dir / f"03_market_breadth_{as_of_date}_{slug}.png"
    p4_path = charts_dir / f"04_industry_heatmap_{as_of_date}_{slug}.png"
    p5_path = charts_dir / f"05_excess_returns_{as_of_date}_{slug}.png"

    overview_png = charts_dir / f"market_overview_{as_of_date}_{slug}.png"
    html_path = reports_dir / f"mip_mobile_tearsheet_{as_of_date}_{slug}.html"

    # Canonical paths
    c_overview = reports_dir / "market_overview_chart.png"
    c_html = reports_dir / "mip_mobile_tearsheet.html"

    # Generate each chart
    p1 = generate_rrg_snapshot_chart(sector_data, ind_hist_df=ind_hist_df, output_png=p1_path, universe_label=universe_label)
    p2 = generate_rotation_bump_chart(bars_df, target_date=as_of_date, output_png=p2_path, universe_label=universe_label)
    p3 = generate_market_breadth_multipanel(breadth_hist_df, target_date=as_of_date, output_png=p3_path, universe_label=universe_label)
    p4 = generate_industry_heatmap(bars_df, target_date=as_of_date, output_png=p4_path, universe_label=universe_label)
    p5 = generate_excess_returns_chart(sector_data, output_png=p5_path, universe_label=universe_label)
    p_ov = generate_matplotlib_dashboard(breadth_data, sector_data, top_df, output_png=overview_png, universe_label=universe_label)

    # Copy to canonical
    shutil.copyfile(p_ov, c_overview)

    # Pure HTML Tearsheet fallback
    try:
        generate_pure_html_fallback(breadth_data, sector_data, top_df, out_path=html_path, universe_label=universe_label)
        shutil.copyfile(html_path, c_html)
    except Exception:
        pass

    # Mirror all generated charts to deliverables/
    for p in [p1, p2, p3, p4, p5, p_ov, c_overview]:
        try:
            shutil.copyfile(p, deliv_dir / p.name)
            if android_deliv:
                shutil.copyfile(p, android_deliv / p.name)
        except Exception:
            pass

    return {
        "01_rrg_snapshot": p1,
        "02_rotation_bump": p2,
        "03_market_breadth": p3,
        "04_industry_heatmap": p4,
        "05_excess_returns": p5,
        "market_overview": p_ov,
        "html_tearsheet": html_path,
    }
