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
    scanned_date = top_df.attrs.get("scanned_date") or db_latest

    # Build tearsheet text
    tearsheet_text = format_screener_tearsheet(top_df, breadth, sectors, regime, scanned_date)

    # Build Next-Gen Alpha Overlays text
    overlay_text = ""
    if use_residual_momentum or use_vol_targeting or use_delivery_veto:
        overlay_text = "\n" + "=" * 76 + "\n 🛡️ NEXT-GEN QUANTITATIVE ALPHA OVERLAYS:\n"
        if use_residual_momentum:
            overlay_text += "   • Idiosyncratic Residual Momentum (Blitz et al.): Active (40% Canonical Volar + 60% Idiosyncratic Alpha, 21d Reversal Excluded)\n"
        if use_delivery_veto:
            vetoed = top_df.attrs.get("delivery_vetoed_symbols", [])
            if vetoed:
                overlay_text += f"   • Microstructure Delivery Veto: Filtered {len(vetoed)} distribution candidate(s): {', '.join(vetoed)}\n"
            else:
                overlay_text += "   • Microstructure Delivery Veto: Active (Zero institutional distribution traps detected)\n"
        if use_vol_targeting:
            shield = top_df.attrs.get("shield_scalar", 1.0)
            r_vol = top_df.attrs.get("market_realized_vol", 0.15)
            overlay_text += f"   • Dynamic Volatility Cash Shield: Exposure scaled to {shield*100:.1f}% Equity / {(1-shield)*100:.1f}% Liquid Cash\n     (Market Realized Vol: {r_vol*100:.1f}% vs Target: 12.0%)\n"
        overlay_text += "=" * 76 + "\n"

    # Build database audit text
    db_audit = top_df.attrs.get("db_audit")
    audit_text = ""
    if db_audit:
        if db_audit.get("is_updated"):
            audit_text = (
                "\n" + "=" * 76 + "\n"
                "💾 DATABASE AUDIT: 🟢 UPDATED WITH NEW MARKET SESSIONS!\n"
                f"  • New Rows Added:  +{db_audit.get('new_rows_added', 0):,} rows committed to SQLite\n"
                f"  • Date Transition: {db_audit.get('pre_latest_date')} ➔ {db_audit.get('post_latest_date')}\n"
                f"  • Total Rows:      {db_audit.get('post_row_count', 0):,} rows in prices table\n"
                + ("  • Google Drive:    ✓ Backed up to /MyDrive/MIP/universe.db.gz\n" if db_audit.get("gdrive_backed_up") else "")
                + "=" * 76
            )
        else:
            audit_text = (
                "\n" + "=" * 76 + "\n"
                "💾 DATABASE AUDIT: 🔵 ALREADY UP-TO-DATE (No new sessions available)\n"
                f"  • Latest Session:  {db_audit.get('post_latest_date')}\n"
                f"  • Total Rows:      {db_audit.get('post_row_count', 0):,} rows in prices table\n"
                + "=" * 76
            )

    # Render Plot to base64 image (Dynamic sizing, prevent figure leak warning)
    chart_html = ""
    plt.close("all")
    if top_df is not None and not top_df.empty and "volar_score" in top_df.columns:
        fig = plt.figure(figsize=(10, 4.5), dpi=100)
        plot_data = top_df.head(10).sort_values("volar_score", ascending=True)
        plt.barh(plot_data["symbol"], plot_data["volar_score"], color="#00adb5")
        plt.title(f"Top 10 Momentum Candidates [{universe}] ({scanned_date})", fontsize=12, fontweight="bold")
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

    # Render collapsible output (Hidden by default, reveals on click)
    full_log_text = (
        f"Market State: Latest Expected EOD: {expected_session} | Database Latest: {db_latest}\n"
        f"Configuration: Top {top_n} | Excel: {generate_excel} | Telegram: {send_telegram} | Auto-DL: {auto_download_excel}\n\n"
        + tearsheet_text
        + (("\n" + overlay_text) if overlay_text else "")
        + "\n"
        + audit_text
        + (f"\n\n{dl_notice}" if dl_notice else "")
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
