"""
colab/dashboard.py - Multi-Architecture C99 SIMD Backtesting & Brute Force Dashboard for Google Colab
Modularizes Cell 3 into a clean, testable routine.
"""

import os
import sys
import time
import io
import base64
from pathlib import Path
from typing import Optional, Dict, Any
import matplotlib.pyplot as plt
import numpy as np
try:
    import ipywidgets as widgets
    from IPython.display import display, clear_output, HTML
except ImportError:
    widgets = None
    def display(obj):
        pass
    def clear_output(wait=False):
        pass
    def HTML(data):
        return data

from brute_force.bridge import compile_native_kernel
from brute_force.runner import BruteForceCampaignRunner
from scripts.scanner_hardening import trigger_colab_download

_bf_runner_instance: Optional[BruteForceCampaignRunner] = None


def get_runner_instance() -> BruteForceCampaignRunner:
    """Maintains singleton runner instance in RAM to reuse cached TensorCube."""
    global _bf_runner_instance
    if _bf_runner_instance is None:
        _bf_runner_instance = BruteForceCampaignRunner()
    return _bf_runner_instance


def render_backtest_dashboard() -> Any:
    """
    Renders the interactive Backtesting & Parallel Brute Force Sweep Cockpit in Google Colab.
    """
    if widgets is None:
        print("⚠ ipywidgets is not installed. Interactive dashboard is available in Google Colab / Jupyter.")
        return None

    # Clean up any lingering figures from previous runs
    plt.close("all")

    # 1. Compile or load native C99 SIMD kernel (AVX2/NEON)
    so_path = compile_native_kernel(force_recompile=False)
    print(f"✓ Native SIMD Kernel active: {so_path.name} ({so_path.stat().st_size:,} bytes)")

    runner = get_runner_instance()

    # 2. Interactive UI Controls
    w_engine_mode = widgets.RadioButtons(
        options=["🎯 Custom Date & Parameter Backtest", "⚡ Parallel Brute Force Optimization Sweep"],
        value="🎯 Custom Date & Parameter Backtest",
        description="Engine Mode:",
        layout={"width": "max-content"},
    )

    # Mode 1 Controls: Custom Date Backtest
    era_presets = {
        "Full 10-Year (2016–2026)": ("2016-01-01", "2026-08-31"),
        "Post-COVID Bull (2020–2024)": ("2020-04-01", "2024-12-31"),
        "COVID Crash & Recovery (2020)": ("2020-01-01", "2020-09-30"),
        "Recent 2-Year (2024–2026)": ("2024-01-01", "2026-10-14"),
        "Mid-Cap Bear (2018–2019)": ("2018-01-01", "2019-12-31"),
        "Custom Dates": ("", ""),
    }

    w_bt_preset = widgets.Dropdown(options=list(era_presets.keys()), value="Full 10-Year (2016–2026)", description="Era Preset:")
    w_bt_start = widgets.Text(value="2016-01-01", description="Start Date:")
    w_bt_end = widgets.Text(value="2026-08-31", description="End Date:")
    w_bt_universe = widgets.Dropdown(options=["NIFTY750", "NIFTY500", "ALL"], value="NIFTY750", description="Universe:")
    w_bt_schedule = widgets.Dropdown(options=["monthly", "weekly", "quarterly", "half_yearly", "yearly"], value="monthly", description="Schedule:")
    w_bt_top_n = widgets.IntSlider(value=20, min=5, max=50, step=5, description="Top N:")
    w_bt_lookback = widgets.Dropdown(options=[126, 189, 252, 315], value=252, description="Lookback:")
    w_bt_ema = widgets.Dropdown(options=[50, 100, 150, 200, 250], value=200, description="EMA Trend:")
    w_bt_retrace = widgets.FloatSlider(value=0.80, min=0.60, max=0.95, step=0.05, description="Retrace:")
    w_bt_sector_cap = widgets.IntSlider(value=2, min=1, max=5, description="Max/Sector:")
    w_bt_sizing = widgets.Dropdown(options=["atr_risk_parity", "equal_weight"], value="atr_risk_parity", description="Sizing Mode:")

    w_alpha_res = widgets.Checkbox(value=False, description="Residual Momentum (Blitz 2011)")
    w_alpha_vol = widgets.Checkbox(value=False, description="EWMA Vol Targeting (Harvey 2018)")
    w_alpha_flow = widgets.Checkbox(value=False, description="Delivery Flow Absorption Veto")

    w_btn_run_bt = widgets.Button(description="🚀 Run Custom Backtest", button_style="primary", icon="play")

    # Mode 2 Controls: Brute Force Parameter Sweep
    sweep_presets = [
        "Tier 1: Multi-Era & Multi-Schedule Sweep (35 runs)",
        "Tier 2: Systematic Filter Ablation (44 runs)",
        "Tier 3: Rapid Neighborhood Grid (810 runs)",
        "Tier 3: Deep Comprehensive Grid (10,000 runs)",
        "Tier 3: Full Factorial Master Matrix (61,440 runs)",
        "Tier 3: Mega Factorial Matrix (250,000 runs)",
        "Tier 3: Ultra Factorial Matrix (1,000,000 runs)",
        "Tier 3: Factorial + Random Time Durations (Deep - 10,000 runs)",
        "Tier 3: Factorial + Random Time Durations (Mega - 250,000 runs)",
        "Tier 3: Factorial + Random Time Durations (Ultra - 1,000,000 runs)",
        "Tier 4: Monte Carlo Walk-Forward & DSR (500 runs)",
        "Custom Parameter Sweep",
    ]
    w_sw_preset = widgets.Dropdown(options=sweep_presets, value="Tier 1: Multi-Era & Multi-Schedule Sweep (35 runs)", description="Sweep Type:")
    w_sw_universe = widgets.Dropdown(options=["NIFTY750", "NIFTY500", "ALL"], value="NIFTY750", description="Universe:")
    w_sw_schedule = widgets.Dropdown(options=["monthly", "weekly", "quarterly", "half_yearly", "yearly"], value="monthly", description="Schedule:")
    w_sw_start = widgets.Text(value="2016-01-01", description="Start Date:")
    w_sw_end = widgets.Text(value="2026-08-31", description="End Date:")
    w_sw_threads = widgets.IntSlider(value=min(8, os.cpu_count() or 4), min=1, max=16, description="Threads:")
    w_sw_auto_dl = widgets.Checkbox(value=True, description="Auto-Download CSV 📥")

    w_sw_alpha_res = widgets.Checkbox(value=False, description="Residual Momentum (Blitz 2011)")
    w_sw_alpha_vol = widgets.Checkbox(value=False, description="EWMA Vol Targeting (Harvey 2018)")
    w_sw_alpha_flow = widgets.Checkbox(value=False, description="Delivery Flow Absorption Veto")
    w_sw_durations = widgets.Checkbox(value=False, description="Random Time Durations Dimension 🎲")

    w_btn_run_sw = widgets.Button(description="⚡ Launch Parallel C99 Sweep", button_style="warning", icon="bolt")

    w_output_bt = widgets.Output()

    def on_preset_changed(change):
        if change["new"] in era_presets and change["new"] != "Custom Dates":
            s, e = era_presets[change["new"]]
            w_bt_start.value = s
            w_bt_end.value = e

    w_bt_preset.observe(on_preset_changed, names="value")

    box_backtest = widgets.VBox([
        widgets.HBox([w_bt_preset, w_bt_universe]),
        widgets.HBox([w_bt_start, w_bt_end]),
        widgets.HBox([w_bt_schedule, w_bt_top_n]),
        widgets.HBox([w_bt_lookback, w_bt_ema]),
        widgets.HBox([w_bt_retrace, w_bt_sector_cap]),
        widgets.HBox([w_bt_sizing]),
        widgets.HBox([w_alpha_res, w_alpha_vol, w_alpha_flow]),
        w_btn_run_bt,
    ])

    box_sweep = widgets.VBox([
        widgets.HBox([w_sw_preset, w_sw_universe]),
        widgets.HBox([w_sw_schedule, w_sw_threads]),
        widgets.HBox([w_sw_start, w_sw_end]),
        widgets.HBox([w_sw_alpha_res, w_sw_alpha_vol, w_sw_alpha_flow]),
        widgets.HBox([w_sw_durations, w_sw_auto_dl]),
        w_btn_run_sw,
    ])

    ui_container = widgets.VBox([box_backtest])

    def on_mode_changed(change):
        if "Custom" in change["new"]:
            ui_container.children = [box_backtest]
        else:
            ui_container.children = [box_sweep]

    w_engine_mode.observe(on_mode_changed, names="value")

    _bt_is_running = [False]

    def handle_run_backtest(b):
        if _bt_is_running[0]:
            return
        _bt_is_running[0] = True
        w_btn_run_bt.disabled = True
        _orig_bt_desc = w_btn_run_bt.description
        w_btn_run_bt.description = "⏳ Simulating..."
        with w_output_bt:
            clear_output()
            print(f"🚀 Initializing C99 Custom Backtest [{w_bt_universe.value}]...")
            print(f"  • Date Span:  {w_bt_start.value} ➔ {w_bt_end.value} ({w_bt_schedule.value})")
            print(f"  • Parameters: Lookback={w_bt_lookback.value}d | EMA={w_bt_ema.value}d | Top {w_bt_top_n.value} | Retrace={w_bt_retrace.value:.2f} | Max/Sec={w_bt_sector_cap.value}")
            print(f"  • Sizing:     {w_bt_sizing.value} | Alphas: ResMom={w_alpha_res.value}, VolTarget={w_alpha_vol.value}, Delivery={w_alpha_flow.value}")
            t0 = time.perf_counter()
            try:
                res = runner.run_custom_backtest(
                    start_date=w_bt_start.value,
                    end_date=w_bt_end.value or None,
                    universe_name=w_bt_universe.value,
                    schedule=w_bt_schedule.value,
                    lookback=w_bt_lookback.value,
                    ema_trend=w_bt_ema.value,
                    top_n=w_bt_top_n.value,
                    retrace_threshold=w_bt_retrace.value,
                    max_per_sector=w_bt_sector_cap.value,
                    sizing_mode=w_bt_sizing.value,
                    use_residual_mom=w_alpha_res.value,
                    use_vol_targeting=w_alpha_vol.value,
                    use_delivery_veto=w_alpha_flow.value,
                )
                elapsed_ms = (time.perf_counter() - t0) * 1000.0

                tearsheet_text = (
                    "=" * 76 + "\n"
                    f" PROJECT MIP: INSTITUTIONAL TEARSHEET ({res.get('start_date', w_bt_start.value)} ➔ {res.get('end_date', w_bt_end.value)})\n"
                    + "=" * 76 + "\n"
                    f"  • Initial Capital:    ₹{res.get('initial_capital', 1_000_000.0):,.2f}\n"
                    f"  • Ending Capital:     ₹{res['ending_equity']:,.2f} (Total Return: {((res['ending_equity']/max(1.0, res.get('initial_capital', 1_000_000.0)))-1)*100:+.2f}%)\n"
                    f"  • Annualized CAGR:    {res['cagr_pct']:+.2f}%\n"
                    f"  • Sharpe Ratio:       {res['sharpe_ratio']:.2f}\n"
                    f"  • Sortino Ratio:      {res['sortino_ratio']:.2f}\n"
                    f"  • Calmar Ratio:       {res['calmar_ratio']:.2f}\n"
                    f"  • Maximum Drawdown:   {res['max_drawdown_pct']:.2f}%\n"
                    f"  • Win Rate:           {res['win_rate_pct']:.1f}% ({res.get('winning_trades', 0)} wins / {res.get('total_trades', 0)} trades)\n"
                    f"  • Annual Turnover:    {res['turnover_annual_pct']:.1f}%\n"
                    f"  • C99 SIMD Latency:   {res['sim_latency_ms']:.2f} ms (Total compute: {elapsed_ms:.1f} ms)\n"
                    + "=" * 76
                )

                # Plot Equity Curve & Underwater Drawdown
                plt.close("all")
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), dpi=100, gridspec_kw={"height_ratios": [2.5, 1.2]}, sharex=True)
                dates = pd.to_datetime(res["rebalance_dates"])
                eq = np.array(res["equity_curve"])
                bench = np.array(res.get("benchmark_equity", eq))
                dd = np.array(res.get("drawdown_pct_series", np.zeros_like(eq)))

                ax1.plot(dates, eq, label=f"MIP Strategy ({res['universe']}) [CAGR: {res['cagr_pct']:+.1f}%]", color="#00adb5", lw=2.2)
                ax1.plot(dates, bench, label="NIFTY 500 Benchmark", color="#ff79c6", lw=1.6, ls="--", alpha=0.85)
                ax1.set_title(f"MIP Institutional Backtest • {res['universe']} ({res['start_date']} to {res['end_date']})", fontsize=13, fontweight="bold")
                ax1.set_ylabel("Portfolio Value (₹)", fontsize=11)
                ax1.grid(True, alpha=0.25, ls=":")
                ax1.legend(loc="upper left", frameon=True)
                ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"₹{x:,.0f}"))

                ax2.fill_between(dates, dd, 0, color="#ff5555", alpha=0.4, label=f"Underwater Drawdown (Max: {res['max_drawdown_pct']:.1f}%)")
                ax2.plot(dates, dd, color="#ff5555", lw=1.2)
                ax2.set_ylabel("Drawdown %", fontsize=11)
                ax2.set_xlabel("Rebalance Date", fontsize=11)
                ax2.grid(True, alpha=0.25, ls=":")
                ax2.legend(loc="lower left", frameon=True)
                ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f"{x:.0f}%"))

                plt.tight_layout()
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
                plt.close("all")
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode("utf-8")
                chart_html = f'<div style="text-align: center; margin-top: 15px;"><img src="data:image/png;base64,{img_b64}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);" /></div>'

                display(HTML(f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 10px 0;">
  <div style="background: #1e1e2e; border: 1px solid #45475a; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
    <div style="color: #a6e3a1; font-weight: bold; font-size: 14px;">
      ✅ Backtest Complete: <span style="color: #cdd6f4;">{res['universe']}</span> • CAGR: <span style="color: #f9e2af;">{res['cagr_pct']:+.2f}%</span> • Sharpe: <span style="color: #89b4fa;">{res['sharpe_ratio']:.2f}</span> • Max DD: <span style="color: #f38ba8;">{res['max_drawdown_pct']:.2f}%</span>
    </div>
  </div>
  <details open style="background: #11111b; border: 1px solid #313244; border-radius: 8px; padding: 12px; cursor: pointer;">
    <summary style="font-weight: bold; font-size: 14px; color: #00adb5; padding: 4px 8px; outline: none; user-select: none;">
      ▶ 📈 Tearsheet & Equity / Drawdown Curve
    </summary>
    <div style="margin-top: 12px; cursor: default;">
      {chart_html}
      <pre style="background: #181825; border: 1px solid #313244; border-radius: 6px; padding: 12px; font-family: 'Fira Code', Menlo, Consolas, monospace; font-size: 12px; color: #cdd6f4; white-space: pre-wrap; word-break: break-word; overflow-x: auto; margin-top: 15px;">{tearsheet_text}</pre>
    </div>
  </details>
</div>
"""))
            except Exception as e:
                print(f"❌ Backtest Error: {e}")
            finally:
                w_btn_run_bt.disabled = False
                w_btn_run_bt.description = _orig_bt_desc
                _bt_is_running[0] = False

    _sw_is_running = [False]

    def handle_run_sweep(b):
        if _sw_is_running[0]:
            return
        _sw_is_running[0] = True
        w_btn_run_sw.disabled = True
        _orig_sw_desc = w_btn_run_sw.description
        w_btn_run_sw.description = "⏳ Running C99 Sweep..."
        with w_output_bt:
            clear_output()
            print(f"⚡ Launching C99 SIMD Parallel Parameter Sweep [{w_sw_preset.value}]...")
            print(f"  • Universe: {w_sw_universe.value} | Threads: {w_sw_threads.value}")
            print(f"  • Overlays: Residual={w_sw_alpha_res.value}, VolTarget={w_sw_alpha_vol.value}, Delivery={w_sw_alpha_flow.value}, Durations={w_sw_durations.value}")
            t0 = time.perf_counter()
            try:
                has_durations = w_sw_durations.value or ("Durations" in w_sw_preset.value) or ("Random" in w_sw_preset.value)
                if "Tier 1" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier1",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                    )
                elif "Tier 2" in w_sw_preset.value or "Ablation" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier2",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                    )
                elif "Tier 4" in w_sw_preset.value or "Monte Carlo" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier4",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                    )
                elif "Ultra" in w_sw_preset.value or "1,000,000" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier3_ultra_durations" if has_durations else "tier3_ultra",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                        include_random_durations=has_durations,
                    )
                elif "Mega" in w_sw_preset.value or "250,000" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier3_mega_durations" if has_durations else "tier3_mega",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                        include_random_durations=has_durations,
                    )
                elif "Full Factorial" in w_sw_preset.value or "61,440" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier3_full",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                    )
                elif "Deep" in w_sw_preset.value or "10,000" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier3_deep_durations" if has_durations else "tier3_deep",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                        include_random_durations=has_durations,
                    )
                elif "Tier 3" in w_sw_preset.value or "Rapid" in w_sw_preset.value:
                    df = runner.run_grid_preset(
                        preset="tier3_rapid",
                        universe_name=w_sw_universe.value,
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                    )
                else:
                    df = runner.run_custom_sweep(
                        start_date=w_sw_start.value,
                        end_date=w_sw_end.value or None,
                        universe_name=w_sw_universe.value,
                        schedules=[w_sw_schedule.value],
                        num_threads=w_sw_threads.value,
                        use_residual_mom=w_sw_alpha_res.value,
                        use_vol_targeting=w_sw_alpha_vol.value,
                        use_delivery_veto=w_sw_alpha_flow.value,
                        include_random_durations=has_durations,
                    )

                elapsed_s = time.perf_counter() - t0
                sims_per_sec = len(df) / max(0.001, elapsed_s)

                top10 = df.head(10).copy()
                cols_to_show = [c for c in ["param_id", "duration_name", "lookback", "ema_trend", "top_n", "retrace_threshold", "cagr", "sharpe", "sortino", "max_drawdown", "win_rate", "ending_equity"] if c in top10.columns]
                sweep_summary_text = (
                    f"✓ Optimization Sweep Complete: {len(df):,} parameter sets evaluated in {elapsed_s:.2f}s ({sims_per_sec:,.0f} sims/sec)\n\n"
                    "🏆 TOP 10 OPTIMAL PARAMETER CONFIGURATIONS (RANKED BY SHARPE):\n"
                    + top10[cols_to_show].to_string(index=False)
                )

                out_dir = Path("reports/brute_force")
                out_dir.mkdir(parents=True, exist_ok=True)
                csv_path = out_dir / "brute_force_sweep_results.csv"
                df.to_csv(csv_path, index=False)
                dl_notice = f"✓ Sweep Dataset Saved: {csv_path.name} ({len(df)} rows)"

                plt.close("all")
                fig = plt.figure(figsize=(10, 4.5), dpi=100)
                top_plot = top10.sort_values("sharpe", ascending=True)
                labels = [f"LB={int(r['lookback'])}d EMA={int(r['ema_trend'])}d N={int(r['top_n'])}" for _, r in top_plot.iterrows()]
                plt.barh(labels, top_plot["sharpe"], color="#00adb5")
                plt.title("Top 10 Configurations — Sharpe Ratio Distribution", fontsize=12, fontweight="bold")
                plt.xlabel("Annualized Sharpe Ratio", fontsize=10)
                plt.grid(axis="x", linestyle=":", alpha=0.5)
                plt.tight_layout()

                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
                plt.close("all")
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode("utf-8")
                chart_html = f'<div style="text-align: center; margin-top: 15px;"><img src="data:image/png;base64,{img_b64}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);" /></div>'

                if w_sw_auto_dl.value:
                    try:
                        dl_ok = trigger_colab_download(csv_path, cooldown_seconds=20.0)
                        dl_notice += " (Downloaded)" if dl_ok else " (Ready on disk)"
                    except Exception as e_dl:
                        dl_notice += f" (Note: {e_dl})"

                best_sharpe = top10.iloc[0]['sharpe'] if not top10.empty and 'sharpe' in top10.columns else 0.0
                best_cagr = top10.iloc[0]['cagr'] if not top10.empty and 'cagr' in top10.columns else 0.0
                display(HTML(f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 10px 0;">
  <div style="background: #1e1e2e; border: 1px solid #45475a; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
    <div style="color: #a6e3a1; font-weight: bold; font-size: 14px;">
      ✅ Sweep Complete: <span style="color: #cdd6f4;">{len(df):,} configurations</span> • Top Sharpe: <span style="color: #89b4fa;">{best_sharpe:.2f}</span> • Top CAGR: <span style="color: #f9e2af;">{best_cagr:+.2f}%</span> • Elapsed: <span style="color: #cba6f7;">{elapsed_s:.2f}s</span>
    </div>
    <div style="font-size: 12px; color: #89b4fa;">
      {dl_notice}
    </div>
  </div>
  <details open style="background: #11111b; border: 1px solid #313244; border-radius: 8px; padding: 12px; cursor: pointer;">
    <summary style="font-weight: bold; font-size: 14px; color: #00adb5; padding: 4px 8px; outline: none; user-select: none;">
      ▶ 🏆 Top 10 Configurations & Parameter Chart
    </summary>
    <div style="margin-top: 12px; cursor: default;">
      {chart_html}
      <pre style="background: #181825; border: 1px solid #313244; border-radius: 6px; padding: 12px; font-family: 'Fira Code', Menlo, Consolas, monospace; font-size: 12px; color: #cdd6f4; white-space: pre-wrap; word-break: break-word; overflow-x: auto; margin-top: 15px;">{sweep_summary_text}\n\n{dl_notice}</pre>
    </div>
  </details>
</div>
"""))
            except Exception as e:
                print(f"❌ Sweep Error: {e}")
            finally:
                w_btn_run_sw.disabled = False
                w_btn_run_sw.description = _orig_sw_desc
                _sw_is_running[0] = False

    try:
        w_btn_run_bt.on_click(handle_run_backtest, remove=True)
        w_btn_run_sw.on_click(handle_run_sweep, remove=True)
    except Exception:
        pass
    w_btn_run_bt.on_click(handle_run_backtest)
    w_btn_run_sw.on_click(handle_run_sweep)

    dashboard_layout = widgets.VBox([
        w_engine_mode,
        ui_container,
        w_output_bt,
    ])
    display(dashboard_layout)
    return dashboard_layout
