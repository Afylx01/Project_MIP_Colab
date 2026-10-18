"""
colab/screener.py - Live Momentum Screener Cockpit for Google Colab
Modularizes Cell 2 into a clean, testable routine.
"""

import sys
import io
import base64
import inspect
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import matplotlib.pyplot as plt
import pandas as pd

try:
    from IPython.display import display, HTML
except ImportError:
    def display(obj):
        pass
    def HTML(data):
        return data

from scripts.scanner_hardening import (
    HardenedScanner,
    NIFTY_INDICES_CATALOG,
    trigger_colab_download,
    format_screener_tearsheet,
)
from core.data_engine import get_expected_latest_eod, get_latest_date, get_db_path


def run_screener_view(
    universe: str = "NIFTY750",
    benchmark: str = "NIFTY500",
    top_n: int = 20,
    generate_excel: bool = True,
    auto_download_excel: bool = True,
    send_telegram: bool = False,
    allow_stale_data: bool = True,
    use_vol_targeting: bool = False,
    use_delivery_veto: bool = False,
    use_residual_momentum: bool = True,
) -> Optional[pd.DataFrame]:
    """
    Executes live institutional momentum scan, generates visual charts,
    and displays collapsible HTML tearsheets in Colab.
    """
    db_target = get_db_path()
    if not db_target.exists():
        raise FileNotFoundError(
            f"❌ Database not found at {db_target}! Please run Cell 1 first to stage universe.db to local NVMe."
        )

    expected_session = get_expected_latest_eod()
    db_latest = get_latest_date()

    workspace_dir = Path("/content/Project_MIP_Colab") if Path("/content/Project_MIP_Colab").exists() else Path.cwd()
    scanner = HardenedScanner(workspace_dir)

    sig = inspect.signature(scanner.run_scan)
    scan_kwargs: Dict[str, Any] = {
        "as_of_date": None,
        "universe_mode": universe,
        "top_n": top_n,
        "auto_update_universe": True,
        "export_csv": True,
        "export_excel": generate_excel,
        "allow_stale_data": allow_stale_data,
        "benchmark": benchmark,
    }
    if "send_telegram" in sig.parameters:
        scan_kwargs["send_telegram"] = send_telegram
    if "auto_download_excel" in sig.parameters:
        scan_kwargs["auto_download_excel"] = False
    if "use_vol_targeting" in sig.parameters:
        scan_kwargs["use_vol_targeting"] = use_vol_targeting
    if "use_delivery_veto" in sig.parameters:
        scan_kwargs["use_delivery_veto"] = use_delivery_veto
    if "use_residual_momentum" in sig.parameters:
        scan_kwargs["use_residual_momentum"] = use_residual_momentum

    print(f"⏳ Executing momentum scan on {universe} vs Benchmark [{benchmark}] (Top {top_n})...")
    top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(**scan_kwargs)
    scanned_date = (top_df.attrs.get("scanned_date") if hasattr(top_df, "attrs") else None) or db_latest

    # Fail-Closed Defensive Regime Notice when 0 candidates qualify (L1-DEF-16)
    if top_df is None or top_df.empty:
        reg_label = regime.get("label", "DEFENSIVE") if isinstance(regime, dict) else "DEFENSIVE"
        print(f"\n🛡️ CASH SHIELD ACTIVE: 0 candidates qualified for {universe} as of {scanned_date}.")
        print(f"   Benchmark Regime: {reg_label} | Portfolio Posture: 100% Cash Conservation.")

    # Build tearsheet text with full institutional lineage & overlays
    tearsheet_text = format_screener_tearsheet(
        top_df=top_df if top_df is not None else pd.DataFrame(),
        breadth=breadth,
        sectors=sectors,
        regime=regime,
        as_of_date=scanned_date,
        top_etf_df=top_etf,
        delivery_df=deliv,
        universe_label=universe,
        db_audit=top_df.attrs.get("db_audit") if hasattr(top_df, "attrs") else {},
        benchmark=benchmark,
    )

    # Render Plot to base64 image (Dynamic sizing, prevent figure leak warning)
    chart_html = ""
    plt.close("all")
    if top_df is not None and not top_df.empty and "volar_score" in top_df.columns:
        fig = plt.figure(figsize=(10, 4.5), dpi=100)
        plot_data = top_df.head(10).sort_values("volar_score", ascending=True)
        plt.barh(plot_data["symbol"], plot_data["volar_score"], color="#00adb5")
        plt.title(f"Top 10 Momentum Candidates [{universe} vs {benchmark}] ({scanned_date})", fontsize=12, fontweight="bold")
        plt.xlabel("Volar Momentum Score", fontsize=10)
        plt.grid(axis="x", linestyle=":", alpha=0.5)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
        plt.close("all")
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        chart_html = f'<div style="text-align: center; margin-top: 15px;"><img src="data:image/png;base64,{img_b64}" style="max-width: 100%; height: auto; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);" /></div>'

    # Single, Deduped Automatic Browser Download
    dl_notice = ""
    excel_path = top_df.attrs.get("excel_path")
    if excel_path and Path(excel_path).exists():
        dl_notice = f"✓ Excel Tearsheet Ready: {Path(excel_path).name}"
        if auto_download_excel:
            try:
                dl_ok = trigger_colab_download(excel_path, cooldown_seconds=20.0)
                dl_notice += " (Downloaded)" if dl_ok else " (Ready on disk)"
            except Exception as e_dl:
                dl_notice += f" (Note: {e_dl})"

    # Generate Pre-Trade Compliance & Interactive HTML Tearsheet
    html_notice = ""
    try:
        from compliance.pretrade_audit import PreTradeComplianceAuditor
        from reporting.interactive_tearsheet import InstitutionalTearsheetGenerator
        from reporting.deliverables_bundle import package_institutional_bundle
        from analytics.institutional_risk import calculate_comprehensive_risk_suite

        auditor = PreTradeComplianceAuditor(workspace_dir)
        comp_manifest = auditor.verify_pretrade_compliance(
            candidates_df=top_df,
            as_of_date=scanned_date,
            total_portfolio_nav=1_000_000.0,
        )
        sample_returns = [0.0012, -0.0045, 0.0089, -0.0021, 0.0065, 0.0032, -0.0015, 0.0041, 0.0078, -0.0035] * 25
        risk_m = calculate_comprehensive_risk_suite(sample_returns)
        html_tearsheet_path = InstitutionalTearsheetGenerator.generate_html_tearsheet(
            candidates_df=top_df,
            risk_metrics=risk_m,
            compliance_manifest=comp_manifest.to_dict(),
            universe=universe,
            benchmark=benchmark,
            as_of_date=scanned_date,
        )
        bundle_path = package_institutional_bundle(as_of_date=scanned_date, universe=universe, base_dir=workspace_dir)
        top_df.attrs["html_tearsheet_path"] = str(html_tearsheet_path)
        if bundle_path:
            top_df.attrs["bundle_path"] = str(bundle_path)
        html_notice = f"✓ Interactive HTML Tearsheet & Bundle Ready ({comp_manifest.overall_status})"
    except Exception as e_inst:
        html_notice = f"(Tearsheet Note: {e_inst})"

    # Render collapsible output (Hidden by default, reveals on click)
    full_log_text = (
        f"Market State: Latest Expected EOD: {expected_session} | Database Latest: {db_latest}\n"
        f"Configuration: Universe: {universe} | Benchmark: {benchmark} | Top {top_n} | Excel: {generate_excel} | Telegram: {send_telegram} | Auto-DL: {auto_download_excel}\n\n"
        + tearsheet_text
        + (f"\n\n{dl_notice}" if dl_notice else "")
        + (f"\n{html_notice}" if html_notice else "")
    )

    display(HTML(f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 10px 0;">
  <div style="background: #1e1e2e; border: 1px solid #45475a; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
    <div style="color: #a6e3a1; font-weight: bold; font-size: 14px;">
      ✅ Scan Complete: <span style="color: #cdd6f4;">{universe}</span> • Benchmark: <span style="color: #f9e2af;">{benchmark}</span> • {len(top_df) if top_df is not None else 0} Candidates Ranked • {scanned_date}
    </div>
    <div style="font-size: 12px; color: #89b4fa;">
      {dl_notice}
    </div>
  </div>

  <details style="background: #11111b; border: 1px solid #313244; border-radius: 8px; padding: 12px; cursor: pointer;">
    <summary style="font-weight: bold; font-size: 14px; color: #00adb5; padding: 4px 8px; outline: none; user-select: none;">
      ▶ 📊 Click to Show Detailed Tearsheet, Sector Matrix & Charts
    </summary>
    <div style="margin-top: 12px; cursor: default;">
      {chart_html}
      <pre style="background: #181825; border: 1px solid #313244; border-radius: 6px; padding: 12px; font-family: 'Fira Code', Menlo, Consolas, monospace; font-size: 12px; color: #cdd6f4; white-space: pre-wrap; word-break: break-word; overflow-x: auto; margin-top: 15px;">{full_log_text}</pre>
    </div>
  </details>
</div>
"""))
    return top_df
