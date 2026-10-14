#!/usr/bin/env python3
"""
Project MIP: Standalone Pydroid 3 Quantitative Workstation
Directives: DIR-PROD-PYDROID3-PORT-01 (HALT-16), DIR-PROD-PYDROID3-PARITY-01 (HALT-17)

Unified 12-option interactive mobile trading desk engineered for Pydroid 3.
Zero-compiler, pure Python + SQLite standard library architecture.
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
from typing import Optional

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.data_engine import (
    get_db_path,
    get_latest_date,
    get_expected_latest_eod,
    get_universe_statistics,
    get_date_range,
    get_symbols,
    load_symbol_sector_map,
    load_trading_calendar,
    get_connection,
    StaleDataError,
    DataUnavailableError,
)
from core.scanner import PydroidScanner, format_screener_tearsheet
from core.breadth import MarketBreadthEngine
from core.sector_rotation import SectorRotationEngine
from core.visuals import generate_matplotlib_dashboard, generate_plotly_tearsheet
from core.telegram_sender import PydroidTelegramSender, format_telegram_alert
from core.backtest import LightweightBacktester

try:
    from scripts.scanner_hardening import (
        HardenedScanner,
        NIFTY_INDICES_CATALOG,
        normalize_universe_mode,
        get_hardened_universe_label,
        ConstituentReconciliationEngine,
        MarketDataReconciliationEngine,
        ConstituentSourceStatus,
    )
except ImportError:
    HardenedScanner = PydroidScanner
    NIFTY_INDICES_CATALOG = {}
    normalize_universe_mode = lambda u: str(u).upper()
    get_hardened_universe_label = lambda u: str(u).upper()
    ConstituentReconciliationEngine = None
    MarketDataReconciliationEngine = None
    ConstituentSourceStatus = None


# ANSI Styling
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"
C_MAGENTA = "\033[95m"
C_GRAY = "\033[90m"
C_WHITE = "\033[97m"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def print_banner(latest_date: str):
    print(f"{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════════════════╗{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}║           PROJECT MIP — PYDROID 3 MOBILE TRADING DESK                ║{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}║    Standalone Zero-Compiler Edition • Python 3.13 ARM64 • v2.0.0     ║{C_RESET}")
    print(f"{C_BOLD}{C_CYAN}╚══════════════════════════════════════════════════════════════════════╝{C_RESET}")
    print(f" {C_GRAY}Database: universe.db (Indexed SQLite) | Latest EOD: {C_BOLD}{latest_date}{C_RESET}")
    print(f"{C_GRAY}{'─' * 72}{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [1]: Weekly Momentum Scanner (Full Suite)
# ═══════════════════════════════════════════════════════════════════════
def resolve_target_universe(universe_str: Optional[str]) -> str:
    """
    Normalizes any user-entered index code, alias, or string to canonical catalog universe key.
    Defaults to NIFTY500 if None or empty.
    """
    if not universe_str:
        return "NIFTY500"
    u_clean = str(universe_str).strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    if u_clean in ["750", "NIFTY750", "TOTALMARKET", "NIFTYTOTALMARKET", "NIFTY750TOTALMARKET"]:
        return "NIFTY750"
    return normalize_universe_mode(universe_str)



def prompt_universe_selection() -> tuple[str, bool]:
    """
    Interactive 36-Universe Selector with 30-day cache refresh TTL controls.
    Returns: (selected_universe_key, force_refresh_boolean)
    """
    print(f"\n{C_BOLD}── SELECT TARGET UNIVERSE (ALL 36 NIFTY INDICES AVAILABLE) ──{C_RESET}")
    print(f"  {C_BOLD}Quick Picks:{C_RESET}")
    print(f"  {C_GREEN}[ 1]{C_RESET} 🇮🇳  NIFTY 500 (Large, Mid & Smallcap — ~500 Stocks) [Default]")
    print(f"  {C_CYAN}[ 2]{C_RESET} 🌐  NIFTY 750 (Total Market: 500 + Microcap 250 — ~755 Stocks)")
    print(f"  {C_WHITE}[ 3]{C_RESET} 🏢  NIFTY 50 (Bluechips — 50 Stocks)")
    print(f"  {C_WHITE}[ 4]{C_RESET} 🚀  NIFTY Next 50 (Junior Nifty — 50 Stocks)")
    print(f"  {C_BLUE}[ 5]{C_RESET} 🏦  NIFTY Bank (Banking Index — 14 Stocks)")
    print(f"  {C_MAGENTA}[ 6]{C_RESET} 💻  NIFTY IT (Technology Index — 10 Stocks)")
    print(f"  {C_YELLOW}[ 7]{C_RESET} 🚗  NIFTY Auto (Automobile Index — 15 Stocks)")
    print(f"  {C_GREEN}[ 8]{C_RESET} 💊  NIFTY Pharma (Pharmaceutical Index — 20 Stocks)")
    print(f"  {C_RED}[ 9]{C_RESET} ⚡  ALL ACTIVE SCRIPS (Full Point-In-Time Database — ~1,031 Stocks)")
    print(f"\n  {C_BOLD}Categorized Menus & Search:{C_RESET}")
    print(f"  {C_CYAN}[ B]{C_RESET} 📊  Broad Market Indices (15 Universes: 50, Next 50, 100, 200, 500, Midcap, Smallcap...)")
    print(f"  {C_MAGENTA}[ S]{C_RESET} 🏭  Sectoral Indices (14 Universes: Auto, Bank, Fin Services, FMCG, IT, Metal, Pharma...)")
    print(f"  {C_YELLOW}[ T]{C_RESET} 🎯  Thematic Indices (7 Universes: Commodities, Energy, Infra, CPSE, PSE, Services, MNC)")
    print(f"  {C_WHITE}[ Q]{C_RESET} 🔍  Search / Type Any Index Name or Alias (e.g. 'Bank', 'IT', 'Smallcap250', 'Infra')")

    try:
        u_input = input(f"\n{C_BOLD}Select Universe Option [1-9, B, S, T, Q, Default=1]: {C_RESET}").strip()
    except (KeyboardInterrupt, EOFError):
        return "NIFTY500", False

    u_choice = u_input.upper()
    selected_mode = "NIFTY500"

    if u_choice == "2" or u_choice == "750":
        selected_mode = "NIFTY750TOTALMARKET"
    elif u_choice == "3" or u_choice == "50":
        selected_mode = "NIFTY50"
    elif u_choice == "4" or u_choice == "NEXT50":
        selected_mode = "NIFTYNEXT50"
    elif u_choice == "5" or u_choice == "BANK":
        selected_mode = "NIFTYBANK"
    elif u_choice == "6" or u_choice == "IT":
        selected_mode = "NIFTYIT"
    elif u_choice == "7" or u_choice == "AUTO":
        selected_mode = "NIFTYAUTO"
    elif u_choice == "8" or u_choice == "PHARMA":
        selected_mode = "NIFTYPHARMA"
    elif u_choice == "9" or u_choice in ["ALL", "MASTER", "PIT"]:
        selected_mode = "ALL"
    elif u_choice == "B":
        broad_indices = [k for k, v in NIFTY_INDICES_CATALOG.items() if v.get("category") == "Broad Market"]
        print(f"\n{C_BOLD}── BROAD MARKET INDICES ({len(broad_indices)} UNIVERSES) ──{C_RESET}")
        for i, k in enumerate(broad_indices, 1):
            meta = NIFTY_INDICES_CATALOG[k]
            print(f"  [{i:2d}] {meta['name']} (`{k}`) — Expected: {meta['row_bounds'][0]}-{meta['row_bounds'][1]} scrips")
        sub = input(f"\nSelect Broad Market Index [1-{len(broad_indices)}]: ").strip()
        try:
            sub_idx = int(sub) - 1
            if 0 <= sub_idx < len(broad_indices):
                selected_mode = broad_indices[sub_idx]
        except ValueError:
            selected_mode = resolve_target_universe(sub)
    elif u_choice == "S":
        sector_indices = [k for k, v in NIFTY_INDICES_CATALOG.items() if v.get("category") == "Sectoral"]
        print(f"\n{C_BOLD}── SECTORAL INDICES ({len(sector_indices)} UNIVERSES) ──{C_RESET}")
        for i, k in enumerate(sector_indices, 1):
            meta = NIFTY_INDICES_CATALOG[k]
            print(f"  [{i:2d}] {meta['name']} (`{k}`) — Expected: {meta['row_bounds'][0]}-{meta['row_bounds'][1]} scrips")
        sub = input(f"\nSelect Sectoral Index [1-{len(sector_indices)}]: ").strip()
        try:
            sub_idx = int(sub) - 1
            if 0 <= sub_idx < len(sector_indices):
                selected_mode = sector_indices[sub_idx]
        except ValueError:
            selected_mode = resolve_target_universe(sub)
    elif u_choice == "T":
        thematic_indices = [k for k, v in NIFTY_INDICES_CATALOG.items() if v.get("category") == "Thematic"]
        print(f"\n{C_BOLD}── THEMATIC INDICES ({len(thematic_indices)} UNIVERSES) ──{C_RESET}")
        for i, k in enumerate(thematic_indices, 1):
            meta = NIFTY_INDICES_CATALOG[k]
            print(f"  [{i:2d}] {meta['name']} (`{k}`) — Expected: {meta['row_bounds'][0]}-{meta['row_bounds'][1]} scrips")
        sub = input(f"\nSelect Thematic Index [1-{len(thematic_indices)}]: ").strip()
        try:
            sub_idx = int(sub) - 1
            if 0 <= sub_idx < len(thematic_indices):
                selected_mode = thematic_indices[sub_idx]
        except ValueError:
            selected_mode = resolve_target_universe(sub)
    elif u_choice == "Q" or len(u_input) > 1:
        q_in = input(f"\n{C_BOLD}Enter Index Name, Code or Alias (e.g. Bank, IT, Infra, Smallcap250): {C_RESET}").strip() if u_choice == "Q" else u_input
        selected_mode = resolve_target_universe(q_in)
    else:
        selected_mode = "NIFTY500"

    print(f"  ✓ Target Universe Selected: {C_BOLD}{C_GREEN}{get_hardened_universe_label(selected_mode)}{C_RESET}")

    force_refresh = False
    try:
        ttl_in = input(f"\nConstituent Cache TTL: 30-day policy active.\nForce live download from niftyindices.com (bypassing 30-day cache)? [y/N]: ").strip().lower()
        if ttl_in in ["y", "yes"]:
            force_refresh = True
            print(f"  • {C_YELLOW}Live refresh forced: Will download fresh CSV from niftyindices.com{C_RESET}")
        else:
            print(f"  • {C_GRAY}Using 30-day cache TTL policy (CACHED-VALID if <= 30.0 days old){C_RESET}")
    except (KeyboardInterrupt, EOFError):
        pass

    return selected_mode, force_refresh


# ═══════════════════════════════════════════════════════════════════════
# Option [1]: Weekly Momentum Scanner (Full Suite across 36 Universes)
# ═══════════════════════════════════════════════════════════════════════
def run_scanner_flow(
    interactive: bool = True,
    universe_mode: Optional[str] = None,
    as_of_date: Optional[str] = None,
    force_refresh: bool = False,
    allow_stale: bool = True,
    auto_sync: bool = True,
):
    clear_screen()
    initial_date = get_latest_date()
    print_banner(initial_date)

    force_live_fetch = force_refresh
    if interactive and not universe_mode:
        selected_mode, force_live_fetch = prompt_universe_selection()
    else:
        selected_mode = resolve_target_universe(universe_mode)

    u_label = get_hardened_universe_label(selected_mode)

    # ── LATEST ACTUAL TRADING DAY EOD RESOLUTION GUARANTEE ──
    expected_session = get_expected_latest_eod()
    db_latest = get_latest_date()

    if as_of_date is not None:
        target_display = as_of_date
        scan_target_date = as_of_date
        effective_allow_stale = allow_stale
    else:
        target_display = f"Latest Actual EOD [{expected_session}]"
        scan_target_date = None  # None forces HardenedScanner to evaluate freshness against expected_session
        effective_allow_stale = allow_stale

        if db_latest < expected_session:
            print(f"\n{C_YELLOW}⚠ NOTICE: Database latest session is {db_latest}, while expected completed EOD session is {expected_session}.{C_RESET}")
            if auto_sync:
                print(f"{C_CYAN}⚡ Auto-synchronizing latest market data from NSE bhavcopy archives...{C_RESET}")

    print(f"\n{C_BOLD}{C_YELLOW}⚡ RUNNING WEEKLY MOMENTUM SCANNER [{u_label}] as of {target_display}...{C_RESET}\n")

    scanner = HardenedScanner(BASE_DIR)
    try:
        top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(
            as_of_date=scan_target_date,
            universe_mode=selected_mode,
            auto_update_universe=auto_sync,
            top_n=20,
            export_csv=True,
            export_excel=True,
            force_constituent_refresh=force_live_fetch,
            allow_stale_universe=True,
            allow_stale_data=effective_allow_stale,
        )
    except (StaleDataError, DataUnavailableError, RuntimeError) as e:
        if interactive and isinstance(e, StaleDataError) and not effective_allow_stale:
            print(f"\n{C_YELLOW}⚠ Latest completed market session ({expected_session}) could not be acquired.{C_RESET}")
            try:
                choice = input(f"Fallback and execute scan on latest available database session ({db_latest})? [y/N]: ").strip().lower()
                if choice in ("y", "yes"):
                    print(f"\n{C_CYAN}Retrying scan on available session {db_latest} (STALE PERMITTED)...{C_RESET}\n")
                    top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(
                        as_of_date=db_latest,
                        universe_mode=selected_mode,
                        auto_update_universe=False,
                        top_n=20,
                        export_csv=True,
                        export_excel=True,
                        force_constituent_refresh=force_live_fetch,
                        allow_stale_universe=True,
                        allow_stale_data=True,
                    )
                else:
                    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")
                    return
            except (KeyboardInterrupt, EOFError):
                return
        else:
            print(f"\n{C_RED}{C_BOLD}╔═══════════════════════════════════════════════════════════════════╗{C_RESET}")
            print(f"{C_RED}{C_BOLD}║ ✗ SCAN ABORTED: FAIL-CLOSED DATA FRESHNESS OR UNIVERSE VIOLATION  ║{C_RESET}")
            print(f"{C_RED}{C_BOLD}╚═══════════════════════════════════════════════════════════════════╝{C_RESET}")
            print(f"{C_YELLOW}{e}{C_RESET}\n")
            if not interactive:
                sys.exit(1)
            input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")
            return


    scanned_date = top_df.attrs.get("scanned_date") or get_latest_date()
    tearsheet = format_screener_tearsheet(
        top_df, breadth, sectors, regime, scanned_date,
        top_etf_df=top_etf, delivery_df=deliv, universe_label=u_label
    )
    print(tearsheet)

    print(f"\n{C_GREEN}✓ Scan completed successfully!{C_RESET}")
    print(f"  • Scanned Market Date: {C_BOLD}{C_GREEN}{scanned_date}{C_RESET}")
    print(f"  • Target Universe:     {C_BOLD}{C_CYAN}{u_label}{C_RESET}")
    print(f"  • Screener CSV:        {BASE_DIR / 'reports' / 'screener_output_live.csv'}")
    excel_path = top_df.attrs.get("excel_path") or (BASE_DIR / 'reports' / f'MIP1_Momentum_Scanner_{scanned_date}.xlsx')
    print(f"  • Institutional Excel: {excel_path}")
    print(f"  • Market Breadth JSON: {BASE_DIR / 'reports' / 'market_breadth_live.json'}")
    print(f"  • Sector Rotation JSON:{BASE_DIR / 'reports' / 'sector_rotation_live.json'}")

    # Automated Executive Telegram Dispatch
    print(f"\n{C_BOLD}{C_BLUE}📱 DISPATCHING AUTOMATED TELEGRAM DELIVERABLES...{C_RESET}")
    try:
        from core.telegram_sender import PydroidTelegramSender, format_telegram_alert
        sender = PydroidTelegramSender()
        if sender.is_configured():
            msg = format_telegram_alert(
                top_df, breadth, sectors, regime, scanned_date,
                top_etf_df=top_etf, delivery_df=deliv, universe_label=u_label
            )
            print("  • Sending executive alert message...")
            sender.send_message(msg)

            # Send charts
            chart_paths = top_df.attrs.get("chart_paths", {})
            ov_chart = chart_paths.get("overview_png") or (BASE_DIR / "reports" / "market_overview_chart.png")
            sec_chart = chart_paths.get("sector_rrg_png") or (BASE_DIR / "reports" / "sector_rotation_history.png")

            if ov_chart and Path(ov_chart).exists():
                print(f"  • Sending market overview chart ({Path(ov_chart).name})...")
                sender.send_photo(Path(ov_chart), caption=f"📊 <b>MIP-1 Market Overview Dashboard ({scanned_date}) [{u_label}]</b>")

            if sec_chart and Path(sec_chart).exists():
                print(f"  • Sending sector rotation RRG chart ({Path(sec_chart).name})...")
                sender.send_photo(Path(sec_chart), caption=f"🔄 <b>NSE Primary Sector RRG Dynamics & 30D Trajectory [{u_label}]</b>")

            # Send Excel workbook
            if excel_path and Path(excel_path).exists():
                print(f"  • Sending institutional 12-sheet Excel ({Path(excel_path).name})...")
                sender.send_document(Path(excel_path), caption=f"📈 <b>MIP-1 Institutional Workbook v5.5.1 ({scanned_date}) [{u_label}]</b>")

            # Send Interactive Plotly HTML Tearsheet
            html_path = chart_paths.get("tearsheet_html") or (BASE_DIR / "reports" / "mip_mobile_tearsheet.html")
            if html_path and Path(html_path).exists():
                print(f"  • Sending interactive tearsheet ({Path(html_path).name})...")
                sender.send_document(Path(html_path), caption=f"🌐 <b>Interactive HTML Tearsheet ({scanned_date}) [{u_label}]</b>")

            print(f"{C_GREEN}✓ Telegram automated dispatch completed successfully!{C_RESET}")
        else:
            print(f"{C_YELLOW}⚠ Telegram bot credentials missing. Automated dispatch skipped.{C_RESET}")
    except Exception as e:
        print(f"{C_RED}⚠ Telegram automated dispatch encountered error: {e}{C_RESET}")

    if interactive:
        input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [2]: Preview Telegram Alert
# ═══════════════════════════════════════════════════════════════════════
def run_telegram_preview():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_BLUE}📱 PREVIEWING LIVE TELEGRAM ALERT PAYLOAD...{C_RESET}\n")

    reports_dir = BASE_DIR / "reports"
    screener_file = reports_dir / "screener_output_live.csv"
    breadth_file = reports_dir / "market_breadth_live.json"
    sector_file = reports_dir / "sector_rotation_live.json"

    scanner = HardenedScanner(BASE_DIR)
    top_etf = None
    deliv = None

    if not (screener_file.exists() and breadth_file.exists() and sector_file.exists()):
        print(f"{C_YELLOW}⚠ Live data not cached. Running scanner first...{C_RESET}")
        top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(as_of_date=latest_date, top_n=20)
    else:
        import pandas as pd
        top_df = pd.read_csv(screener_file)
        with open(breadth_file, "r", encoding="utf-8") as f:
            breadth = json.load(f)
        with open(sector_file, "r", encoding="utf-8") as f:
            sectors = json.load(f)
        regime = scanner.evaluate_regime(latest_date)
        etf_file = reports_dir / "etf_top_picks.csv"
        deliv_file = reports_dir / "delivery_analytics.csv"
        if etf_file.exists():
            top_etf = pd.read_csv(etf_file)
        if deliv_file.exists():
            deliv = pd.read_csv(deliv_file)

    u_label = top_df.attrs.get("universe_label", "NIFTY 500")
    msg = format_telegram_alert(
        top_df, breadth, sectors, regime, latest_date,
        top_etf_df=top_etf, delivery_df=deliv, universe_label=u_label
    )
    sender = PydroidTelegramSender()
    sender.send_message(msg, dry_run=True)

    print(f"\n{C_GRAY}Message Length: {len(msg):,} characters (Telegram Limit: 4,096){C_RESET}")
    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [3]: Dispatch Live Telegram Alert
# ═══════════════════════════════════════════════════════════════════════
def run_telegram_dispatch():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_MAGENTA}⚡ DISPATCHING LIVE TELEGRAM ALERT & DELIVERABLES...{C_RESET}\n")

    sender = PydroidTelegramSender()
    if not sender.is_configured():
        print(f"{C_RED}✗ Telegram credentials not configured in {BASE_DIR / '.env'}!{C_RESET}")
        print("Please edit .env and provide TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")
        input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")
        return

    reports_dir = BASE_DIR / "reports"
    screener_file = reports_dir / "screener_output_live.csv"
    excel_file = reports_dir / f"MIP1_Momentum_Scanner_{latest_date}.xlsx"

    scanner = HardenedScanner(BASE_DIR)
    top_etf = None
    deliv = None

    if not screener_file.exists() or not excel_file.exists():
        print(f"{C_YELLOW}Running scanner to generate latest deliverables...{C_RESET}")
        top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(
            as_of_date=latest_date, top_n=20, export_csv=True, export_excel=True
        )
    else:
        import pandas as pd
        top_df = pd.read_csv(screener_file)
        with open(reports_dir / "market_breadth_live.json", "r", encoding="utf-8") as f:
            breadth = json.load(f)
        with open(reports_dir / "sector_rotation_live.json", "r", encoding="utf-8") as f:
            sectors = json.load(f)
        regime = scanner.evaluate_regime(latest_date)
        etf_file = reports_dir / "etf_top_picks.csv"
        deliv_file = reports_dir / "delivery_analytics.csv"
        if etf_file.exists():
            top_etf = pd.read_csv(etf_file)
        if deliv_file.exists():
            deliv = pd.read_csv(deliv_file)

    u_label = top_df.attrs.get("universe_label", "NIFTY 500")
    msg = format_telegram_alert(
        top_df, breadth, sectors, regime, latest_date,
        top_etf_df=top_etf, delivery_df=deliv, universe_label=u_label
    )
    print("Dispatching executive alert message...")
    ok_msg = sender.send_message(msg)

    chart_png = reports_dir / "market_overview_chart.png"
    if chart_png.exists():
        print("Dispatching market overview chart PNG...")
        sender.send_photo(chart_png, caption=f"📊 Market Overview Chart — {latest_date}")

    if excel_file.exists():
        print("Dispatching institutional 12-sheet Excel workbook...")
        sender.send_document(excel_file, caption=f"📑 Institutional 12-Sheet Momentum Workbook — {latest_date}")
    elif screener_file.exists():
        print("Dispatching screener candidate CSV...")
        sender.send_document(screener_file, caption=f"📁 Screener Candidates — {latest_date}")

    if ok_msg:
        print(f"\n{C_GREEN}✓ Live Telegram notification dispatched successfully!{C_RESET}")
    else:
        print(f"\n{C_RED}✗ Failed to dispatch message to Telegram.{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [4]: Generate Visual Charts & Tearsheets
# ═══════════════════════════════════════════════════════════════════════
def run_visuals_generator():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_GREEN}📊 GENERATING VISUAL CHARTS & TEARSHEETS...{C_RESET}\n")

    reports_dir = BASE_DIR / "reports"
    screener_file = reports_dir / "screener_output_live.csv"
    if not screener_file.exists():
        print(f"{C_YELLOW}Running scanner to generate latest metrics...{C_RESET}")
        scanner = HardenedScanner(BASE_DIR)
        top_df, breadth, sectors, regime, *_ = scanner.run_scan(as_of_date=latest_date, top_n=20)
    else:
        import pandas as pd
        top_df = pd.read_csv(screener_file)
        with open(reports_dir / "market_breadth_live.json", "r", encoding="utf-8") as f:
            breadth = json.load(f)
        with open(reports_dir / "sector_rotation_live.json", "r", encoding="utf-8") as f:
            sectors = json.load(f)

    print("Generating Matplotlib 3-panel graphic...")
    png_path = generate_matplotlib_dashboard(breadth, sectors, top_df)
    print(f"  ✓ Exported: {png_path} ({png_path.stat().st_size:,} bytes)")

    print("\nGenerating interactive HTML tearsheet...")
    html_path = generate_plotly_tearsheet(breadth, sectors, top_df)
    print(f"  ✓ Exported: {html_path} ({html_path.stat().st_size:,} bytes)")

    print(f"\n{C_GREEN}✓ All visual deliverables exported to reports/{C_RESET}")
    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [5]: Lightweight Custom Backtester
# ═══════════════════════════════════════════════════════════════════════
def run_custom_backtest_flow():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_CYAN}💼 LIGHTWEIGHT VECTOR BACKTESTER{C_RESET}\n")

    print(f"Configure Backtest Parameters (Press Enter to accept defaults):")
    start_in = input("  1. Start Date [Default: 2020-01-01]: ").strip() or "2020-01-01"
    end_in = input(f"  2. End Date [Default: {latest_date}]: ").strip() or latest_date
    top_n_in = input("  3. Portfolio Top N [Default: 20]: ").strip() or "20"
    capital_in = input("  4. Initial Capital (₹) [Default: 1000000]: ").strip() or "1000000"

    try:
        top_n = int(top_n_in)
        capital = float(capital_in)
    except ValueError:
        print(f"{C_RED}Invalid inputs! Using defaults.{C_RESET}")
        top_n = 20
        capital = 1_000_000.0

    print(f"\n{C_YELLOW}Running simulation from {start_in} to {end_in}...{C_RESET}")
    bt = LightweightBacktester(BASE_DIR)
    t0 = time.time()
    results = bt.run(
        start_date=start_in,
        end_date=end_in,
        top_n=top_n,
        initial_capital=capital
    )
    elapsed = time.time() - t0

    print(f"\n{C_BOLD}{'=' * 68}{C_RESET}")
    print(f"{C_BOLD} BACKTEST PERFORMANCE SUMMARY ({start_in} to {end_in}){C_RESET}")
    print(f"{C_BOLD}{'=' * 68}{C_RESET}")
    print(f"  Strategy CAGR:       {C_GREEN}{results['cagr_pct']:+.2f}%{C_RESET}")
    print(f"  Benchmark CAGR:      {results['benchmark_cagr_pct']:+.2f}%")
    print(f"  Excess CAGR:         {C_BOLD}{results['excess_cagr_pct']:+.2f}%{C_RESET}")
    print(f"  Sharpe Ratio:        {results['sharpe_ratio']:.2f}")
    print(f"  Sortino Ratio:       {results['sortino_ratio']:.2f}")
    print(f"  Calmar Ratio:        {results['calmar_ratio']:.2f}")
    print(f"  Max Drawdown:        {C_RED}{results['max_drawdown_pct']:.2f}%{C_RESET}")
    print(f"  Total Trades:        {results['total_trades']}")
    print(f"  Trade Win Rate:      {results['win_rate_pct']:.1f}%")
    print(f"  Final Equity:        ₹{results['final_equity']:,.2f}")
    print(f"  Computation Time:    {elapsed:.2f}s")
    print(f"{C_BOLD}{'=' * 68}{C_RESET}")
    print(f"✓ Results saved to reports/backtest_results.json")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [6]: Master Institutional TDD & Verification Suite (9 Tests)
# ═══════════════════════════════════════════════════════════════════════
def run_tdd_suite():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_YELLOW}🛡️ RUNNING MASTER INSTITUTIONAL TEST SUITE (TESTS 01 - 09)...{C_RESET}\n")

    master_runner = BASE_DIR / "tests" / "run_all_tests.py"
    ret = os.system(f'"{sys.executable}" "{master_runner}"')

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [7]: Portfolio Rebalancing & Order Generation
# ═══════════════════════════════════════════════════════════════════════
def run_portfolio_orders():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_GREEN}💰 PORTFOLIO REBALANCING & ORDER GENERATION{C_RESET}\n")

    from core.portfolio import PortfolioManager
    from core.settings import load_investing_settings

    st = load_investing_settings(BASE_DIR)
    def_cap = float(st.get("capital", 1000000.0))
    def_top = int(st.get("top_n", 20))
    def_max_sec = int(st.get("max_per_sector", 2))
    def_mode = str(st.get("sizing_mode", "atr_risk_parity"))

    capital_in = input(f"  Target Capital (₹) [Default: {def_cap:,.0f}]: ").strip() or str(int(def_cap))
    top_n_in = input(f"  Portfolio Size Top N [Default: {def_top}]: ").strip() or str(def_top)

    try:
        capital = float(capital_in)
        top_n = int(top_n_in)
    except ValueError:
        print(f"{C_RED}Invalid inputs! Using defaults.{C_RESET}")
        capital = def_cap
        top_n = def_top

    # Check if screener output exists
    screener_file = BASE_DIR / "reports" / "screener_output_live.csv"
    if not screener_file.exists():
        print(f"{C_YELLOW}Running scanner first to generate candidates...{C_RESET}")
        scanner = PydroidScanner(BASE_DIR)
        scanner.run_scan(as_of_date=latest_date, top_n=top_n, export_csv=True)

    pm = PortfolioManager(BASE_DIR)
    print(f"\n{C_YELLOW}Computing equal-weight allocation with statutory frictions...{C_RESET}")

    orders_df = pm.generate_rebalance_orders(capital=capital, cash=capital, top_n=top_n)
    csv_path = pm.export_orders(orders_df)

    # Display orders
    detail_rows = orders_df[orders_df['action'] != 'SUMMARY']
    summary_rows = orders_df[orders_df['action'] == 'SUMMARY']

    print(f"\n{C_BOLD}{'=' * 72}{C_RESET}")
    print(f"{C_BOLD} REBALANCE ORDER LEDGER — {latest_date} (₹{capital:,.0f} / Top {top_n}){C_RESET}")
    print(f"{C_BOLD}{'=' * 72}{C_RESET}")
    print(f"{'#':>3} {'Action':<6} {'Symbol':<14} {'Sector':<12} {'Price':>10} {'Shares':>8} {'Value':>12} {'Friction':>10}")
    print(f"{'─' * 72}")

    for i, (_, row) in enumerate(detail_rows.iterrows(), 1):
        action_color = C_GREEN if row['action'] == 'BUY' else (C_RED if row['action'] == 'SELL' else C_YELLOW)
        price_str = f"₹{row['close_price']:,.2f}" if not (row.get('close_price') is None or (isinstance(row['close_price'], float) and row['close_price'] != row['close_price'])) else "N/A"
        print(f"{i:>3} {action_color}{row['action']:<6}{C_RESET} {str(row['symbol']):<14} {str(row['sector']):<12} {price_str:>10} {int(row['target_shares']):>8} ₹{row['target_value']:>10,.0f} ₹{row['total_friction']:>8,.0f}")

    if not summary_rows.empty:
        s = summary_rows.iloc[0]
        print(f"{'─' * 72}")
        print(f"{C_BOLD}    TOTAL{' ' * 30}{' ' * 10} {int(s['target_shares']):>8} ₹{s['target_value']:>10,.0f} ₹{s['total_friction']:>8,.0f}{C_RESET}")
        print(f"    {C_CYAN}Total Cost (incl. frictions): ₹{s['total_cost']:,.0f}{C_RESET}")

    print(f"{C_BOLD}{'=' * 72}{C_RESET}")
    print(f"\n{C_GREEN}✓ Orders exported to:{C_RESET}")
    print(f"  • CSV: {csv_path}")
    print(f"  • TXT: {csv_path.with_suffix('.txt')}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [8]: Auto-Fetch Market Data (NSE Bhavcopy Sync)
# ═══════════════════════════════════════════════════════════════════════
def run_auto_fetch():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_MAGENTA}📡 AUTOMATED MARKET DATA FETCHER (NSE BHAVCOPY SYNC){C_RESET}\n")

    from core.auto_fetch import PydroidAutoFetch

    fetcher = PydroidAutoFetch(BASE_DIR)
    missing = fetcher.get_missing_trading_dates()

    print(f"  Current Max Date:   {latest_date}")
    print(f"  Missing Sessions:   {len(missing)}")
    if missing:
        print(f"  Date Range:         {missing[0]} → {missing[-1]}")

    if not missing:
        print(f"\n{C_GREEN}✓ Universe database is already up to date!{C_RESET}")
        input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")
        return

    print(f"\n{C_YELLOW}Options:{C_RESET}")
    print(f"  [1] Dry-Run (simulate without modifying database)")
    print(f"  [2] Live Sync (download & update database)")
    print(f"  [0] Cancel")

    choice = input(f"\n{C_BOLD}Select [0-2]: {C_RESET}").strip()

    if choice == "1":
        print(f"\n{C_YELLOW}Running dry-run simulation...{C_RESET}")
        result = fetcher.sync_universe(dry_run=True)
        print(f"\n{C_GREEN}✓ Dry-run complete. Status: {result.get('status', 'N/A')}{C_RESET}")
    elif choice == "2":
        print(f"\n{C_YELLOW}Starting live data synchronization...{C_RESET}")
        old_mutation_flag = os.environ.get("MIP_ALLOW_PROD_MUTATION")
        try:
            os.environ["MIP_ALLOW_PROD_MUTATION"] = "1"
            result = fetcher.sync_universe(dry_run=False)
            status = result.get('status', 'UNKNOWN')
            if status == 'SUCCESS':
                bars = result.get('bars_added', 0)
                new_max = result.get('end_date', 'N/A')
                print(f"\n{C_GREEN}✓ Synchronization COMPLETE!{C_RESET}")
                print(f"  Bars Added:     {bars:,}")
                print(f"  New Max Date:   {new_max}")
            else:
                print(f"\n{C_YELLOW}Sync result: {status}{C_RESET}")
        except Exception as e:
            print(f"\n{C_RED}✗ Sync failed: {e}{C_RESET}")
        finally:
            if old_mutation_flag is not None:
                os.environ["MIP_ALLOW_PROD_MUTATION"] = old_mutation_flag
            else:
                os.environ.pop("MIP_ALLOW_PROD_MUTATION", None)
    else:
        print("Cancelled.")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [9]: Sync NSE Sector Taxonomy
# ═══════════════════════════════════════════════════════════════════════
def run_sector_sync():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_BLUE}🏭 SYNCHRONIZING OFFICIAL NSE SECTOR TAXONOMY{C_RESET}\n")

    from core.sync_sectors import sync_nse_sectors

    print(f"{C_YELLOW}Downloading official NIFTY Total Market constituent list...{C_RESET}")
    try:
        mapping = sync_nse_sectors(BASE_DIR)
        print(f"\n{C_GREEN}✓ Sector taxonomy synchronized successfully!{C_RESET}")
        print(f"  Symbols Mapped:   {len(mapping):,}")

        # Show sector distribution
        import pandas as pd
        dist = pd.Series(list(mapping.values())).value_counts()
        print(f"\n{C_BOLD}  SECTOR DISTRIBUTION:{C_RESET}")
        for sector, count in dist.items():
            pct = (count / len(mapping)) * 100
            print(f"    {sector:<14} : {count:>4d} ({pct:>5.1f}%)")

        print(f"\n  Exported to: {BASE_DIR / 'data' / 'symbol_sector_map.json'}")
    except Exception as e:
        print(f"\n{C_RED}✗ Sector sync failed: {e}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [10]: Standalone Market Breadth Report
# ═══════════════════════════════════════════════════════════════════════
def run_standalone_breadth():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_CYAN}📈 STANDALONE MARKET BREADTH ANALYSIS{C_RESET}\n")

    engine = MarketBreadthEngine(BASE_DIR)
    print(f"{C_YELLOW}Computing breadth metrics for {latest_date}...{C_RESET}")

    breadth = engine.compute_breadth(as_of_date=latest_date)

    print(f"\n{C_BOLD}{'=' * 60}{C_RESET}")
    print(f"{C_BOLD} NIFTY 500 MARKET BREADTH — {latest_date}{C_RESET}")
    print(f"{C_BOLD}{'=' * 60}{C_RESET}")

    regime = breadth.get('regime', 'Unknown')
    regime_emoji = {'Bullish Expansion': '🟢', 'Selective/Neutral': '🟡', 'Contraction/Defensive': '🔴'}.get(regime, '⚪')

    print(f"  Regime:             {regime_emoji} {regime}")
    print(f"  % > 200 EMA:        {breadth.get('pct_above_ema200', 0):.1f}%")
    print(f"  % > 50 EMA:         {breadth.get('pct_above_ema50', 0):.1f}%")
    print(f"  % > 20 EMA:         {breadth.get('pct_above_ema20', 0):.1f}%")
    print(f"  % Near 52w High:    {breadth.get('pct_near_52w_high_20', 0):.1f}% (within 20%)")
    print(f"  % Near 52w High:    {breadth.get('pct_near_52w_high_5', 0):.1f}% (within 5%)")
    print(f"  New 52w Highs:      {breadth.get('new_52w_highs', 0)}")
    print(f"  New 52w Lows:       {breadth.get('new_52w_lows', 0)}")
    print(f"  Net Highs-Lows:     {breadth.get('net_highs_lows', 0)}")
    print(f"  Active Scrips:      {breadth.get('active_scrips', 0)}")
    print(f"{C_BOLD}{'=' * 60}{C_RESET}")

    # Save standalone report
    report_path = BASE_DIR / "reports" / "market_breadth_live.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(breadth, f, indent=2)
    print(f"\n{C_GREEN}✓ Breadth report saved to {report_path}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [11]: Standalone RRG & Sector Rotation Report
# ═══════════════════════════════════════════════════════════════════════
def run_standalone_sector_rrg():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_MAGENTA}🔄 STANDALONE SECTOR ROTATION & RRG ANALYSIS{C_RESET}\n")

    engine = SectorRotationEngine(BASE_DIR)
    print(f"{C_YELLOW}Computing sector rotation metrics for {latest_date}...{C_RESET}")

    sector_results = engine.compute_sector_rotation(as_of_date=latest_date)

    if isinstance(sector_results, dict) and 'sectors' in sector_results:
        sectors_list = sector_results['sectors']
    elif isinstance(sector_results, list):
        sectors_list = sector_results
    else:
        sectors_list = []

    print(f"\n{C_BOLD}{'=' * 75}{C_RESET}")
    print(f"{C_BOLD} SECTOR ROTATION TABLE — {latest_date}{C_RESET}")
    print(f"{C_BOLD}{'=' * 75}{C_RESET}")
    print(f"{'Sector':<14} {'1M Ret':>8} {'3M Ret':>8} {'Alpha1M':>8} {'Alpha3M':>8} {'Breadth':>8} {'RRG':>12}")
    print(f"{'─' * 75}")

    for sec in sectors_list:
        if isinstance(sec, dict):
            name = sec.get('sector', sec.get('name', 'N/A'))
            ret_1m = sec.get('return_1m', sec.get('ret_1m', 0))
            ret_3m = sec.get('return_3m', sec.get('ret_3m', 0))
            alpha_1m = sec.get('alpha_1m', 0)
            alpha_3m = sec.get('alpha_3m', 0)
            breadth = sec.get('breadth_pct', sec.get('pct_above_200ema', 0))
            rrg_quad = sec.get('rrg_quadrant', sec.get('quadrant', 'N/A'))
            color = C_GREEN if ret_1m > 0 else C_RED
            print(f"{name:<14} {color}{ret_1m:>7.1f}%{C_RESET} {ret_3m:>7.1f}% {alpha_1m:>7.1f}% {alpha_3m:>7.1f}% {breadth:>7.1f}% {rrg_quad:>12}")

    print(f"{C_BOLD}{'=' * 75}{C_RESET}")

    # Save standalone report
    report_path = BASE_DIR / "reports" / "sector_rotation_live.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(sector_results, f, indent=2, default=str)
    print(f"\n{C_GREEN}✓ Sector rotation report saved to {report_path}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [12]: Full Database Integrity Audit
# ═══════════════════════════════════════════════════════════════════════
def run_database_audit():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_YELLOW}🔍 FULL DATABASE INTEGRITY AUDIT{C_RESET}\n")

    import time as _time
    t0 = _time.time()

    stats = get_universe_statistics()
    min_date, max_date = get_date_range()
    symbols = get_symbols()
    calendar = load_trading_calendar()
    sector_map = load_symbol_sector_map()

    print(f"{C_BOLD}{'=' * 65}{C_RESET}")
    print(f"{C_BOLD} DATABASE STATISTICS{C_RESET}")
    print(f"{C_BOLD}{'=' * 65}{C_RESET}")
    print(f"  DB Path:            {stats['db_path']}")
    print(f"  DB Size:            {stats['file_size_mb']:.2f} MB")
    print(f"  Total Rows:         {stats['total_rows']:,}")
    print(f"  Unique Symbols:     {stats['unique_symbols']:,}")
    print(f"  Date Range:         {min_date} → {max_date}")
    print(f"  Delisted Rows:      {stats['delisted_rows']:,}")
    print(f"  Trading Calendar:   {len(calendar):,} dates")
    print(f"  Sector Map:         {len(sector_map):,} symbols mapped")

    # Invariant checks
    print(f"\n{C_BOLD} INVARIANT VERIFICATION{C_RESET}")
    print(f"{'─' * 65}")

    conn = get_connection()
    cursor = conn.cursor()
    all_pass = True

    # 1. Zero null prices
    for col in ['open', 'high', 'low', 'close', 'volume']:
        cursor.execute(f"SELECT COUNT(*) FROM prices WHERE {col} IS NULL;")
        null_count = cursor.fetchone()[0]
        status = f"{C_GREEN}✓ PASS{C_RESET}" if null_count == 0 else f"{C_RED}✗ FAIL ({null_count}){C_RESET}"
        if null_count > 0:
            all_pass = False
        print(f"  Zero NULL {col:<8}: {status}")

    # 2. Positive prices
    for col in ['open', 'high', 'low', 'close']:
        cursor.execute(f"SELECT COUNT(*) FROM prices WHERE {col} <= 0;")
        neg_count = cursor.fetchone()[0]
        status = f"{C_GREEN}✓ PASS{C_RESET}" if neg_count == 0 else f"{C_RED}✗ FAIL ({neg_count}){C_RESET}"
        if neg_count > 0:
            all_pass = False
        print(f"  Positive {col:<8}:  {status}")

    # 3. Zero duplicate (symbol, date) keys
    cursor.execute("SELECT COUNT(*) FROM (SELECT date, symbol FROM prices GROUP BY date, symbol HAVING COUNT(*) > 1);")
    dup_count = cursor.fetchone()[0]
    status = f"{C_GREEN}✓ PASS{C_RESET}" if dup_count == 0 else f"{C_RED}✗ FAIL ({dup_count}){C_RESET}"
    if dup_count > 0:
        all_pass = False
    print(f"  Zero Duplicates:    {status}")

    # 4. Date range sanity
    cursor.execute("SELECT COUNT(DISTINCT date) FROM prices;")
    unique_dates = cursor.fetchone()[0]
    print(f"  Unique Trading Days:{C_GREEN} {unique_dates:,}{C_RESET}")

    # 5. Index presence
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='prices';")
    indices = [r[0] for r in cursor.fetchall()]
    print(f"  Indices Present:    {', '.join(indices)}")

    elapsed = _time.time() - t0
    print(f"\n{C_BOLD}{'=' * 65}{C_RESET}")
    if all_pass:
        print(f"{C_BOLD}{C_GREEN}  🎉 ALL INVARIANTS VERIFIED — DATABASE IS 100% CERTIFIED{C_RESET}")
    else:
        print(f"{C_BOLD}{C_RED}  ❌ INVARIANT FAILURES DETECTED — REVIEW REQUIRED{C_RESET}")
    print(f"  Audit completed in {elapsed:.2f}s")
    print(f"{C_BOLD}{'=' * 65}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [13]: Definedge Momentify ALL-ONE ETF Momentum Scanner
# ═══════════════════════════════════════════════════════════════════════
def run_etf_scanner_flow():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_CYAN}🎯 DEFINEDGE MOMENTIFY ALL-ONE ETF MOMENTUM SCANNER (TOP 7){C_RESET}\n")

    from core.etf_engine import ETFMomentumEngine

    scanner = PydroidScanner(BASE_DIR)
    regime = scanner.evaluate_regime(latest_date)
    is_bullish = regime.get("is_normal_regime", True)

    engine = ETFMomentumEngine(BASE_DIR)
    universe = engine.get_all_one_universe()
    print(f"Loaded Definedge ALL-ONE ETF Universe: {len(universe)} instruments.")
    print(f"Market Regime: {regime.get('label', 'N/A')}")
    print(f"{C_YELLOW}Computing ETF returns, Volar scores, and selecting top 7 non-repeating picks...{C_RESET}\n")

    ranked_df, top_picks_df = engine.run_etf_scan(universe, market_bullish=is_bullish, as_of_date=latest_date)

    print(f"{C_BOLD}{'=' * 76}{C_RESET}")
    print(f"{C_BOLD} TOP 7 NON-REPEATING ETF ALLOCATION PICKS — {latest_date}{C_RESET}")
    print(f"{C_BOLD}{'=' * 76}{C_RESET}")
    print(f"{'#':>2} {'Symbol':<14} {'Asset/Underlying':<24} {'Price':>10} {'Volar':>8} {'1M Ret':>8} {'3M Ret':>8}")
    print(f"{'─' * 76}")

    for i, (_, r) in enumerate(top_picks_df.iterrows(), 1):
        sym = r["symbol"]
        und = str(r.get("underlying", r.get("asset_class", "N/A")))[:23]
        px = float(r.get("price", 0.0))
        volar = float(r.get("volar_score", 0.0))
        r1m = float(r.get("return_1m", 0.0))
        r3m = float(r.get("return_3m", 0.0))
        print(f"{i:>2} {C_GREEN}{sym:<14}{C_RESET} {und:<24} ₹{px:>9.2f} {volar:>7.2f} {r1m:>+7.1f}% {r3m:>+7.1f}%")

    print(f"{C_BOLD}{'=' * 76}{C_RESET}")

    csv_path = BASE_DIR / "reports" / "etf_top_picks.csv"
    top_picks_df.to_csv(csv_path, index=False)
    print(f"\n{C_GREEN}✓ ETF picks exported to: {csv_path}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [14]: High Delivery Volume Spikes & Accumulation Tracker
# ═══════════════════════════════════════════════════════════════════════
def run_delivery_analytics_flow():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_GREEN}📦 HIGH DELIVERY VOLUME SPIKES & ACCUMULATION TRACKER{C_RESET}\n")

    from core.delivery import NSEDeliveryManager
    import datetime

    dt = datetime.datetime.strptime(latest_date, "%Y-%m-%d").date()
    mgr = NSEDeliveryManager(BASE_DIR)

    print(f"Fetching / calculating delivery metrics for {latest_date}...")
    df = mgr.get_delivery_data(dt)

    if df.empty:
        print(f"{C_YELLOW}No delivery data available for {latest_date} (may be holiday/weekend or offline).{C_RESET}")
    else:
        print(f"\n{C_BOLD}{'=' * 76}{C_RESET}")
        print(f"{C_BOLD} TOP DELIVERY SPIKES & INSTITUTIONAL ACCUMULATION — {latest_date}{C_RESET}")
        print(f"{C_BOLD}{'=' * 76}{C_RESET}")
        print(f"{'#':>2} {'Symbol':<14} {'Deliv %':>9} {'Multiplier':>12} {'Deliv Qty':>12} {'Pattern':>14} {'Signal':<12}")
        print(f"{'─' * 76}")

        sort_col = "deliv_times" if "deliv_times" in df.columns else "deliv_per"
        top_deliv = df.sort_values(sort_col, ascending=False).head(20)

        for i, (_, r) in enumerate(top_deliv.iterrows(), 1):
            sym = str(r["symbol"])
            d_per = float(r.get("deliv_per", 0.0))
            d_times = float(r.get("deliv_times", 1.0))
            d_qty = int(r.get("deliv_qty", 0))
            pattern = str(r.get("pattern", "NORMAL"))
            signal = str(r.get("signal", ""))

            p_col = C_GREEN if "ACCUMULATION" in pattern else (C_RED if "DISTRIBUTION" in pattern else C_WHITE)
            print(f"{i:>2} {sym:<14} {d_per:>8.1f}% {d_times:>11.2f}x {d_qty:>12,} {p_col}{pattern:<14}{C_RESET} {signal:<12}")

        print(f"{C_BOLD}{'=' * 76}{C_RESET}")
        csv_path = BASE_DIR / "reports" / "delivery_analytics.csv"
        df.to_csv(csv_path, index=False)
        print(f"\n{C_GREEN}✓ Delivery metrics exported to: {csv_path}{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [15]: Regenerate Institutional 12-Sheet Excel Workbook
# ═══════════════════════════════════════════════════════════════════════
def run_excel_regenerator_flow():
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_BLUE}📑 REGENERATING INSTITUTIONAL 12-SHEET EXCEL WORKBOOK...{C_RESET}\n")

    scanner = HardenedScanner(BASE_DIR)
    print("Running full screener pipeline with Excel compilation enabled...")
    top_df, breadth, sectors, regime, top_etf, deliv = scanner.run_scan(
        as_of_date=latest_date,
        top_n=20,
        export_csv=True,
        export_excel=True
    )

    excel_file = BASE_DIR / "reports" / f"MIP1_Momentum_Scanner_{latest_date}.xlsx"
    if excel_file.exists():
        print(f"\n{C_GREEN}✓ Institutional Excel workbook generated!{C_RESET}")
        print(f"  • File: {excel_file} ({excel_file.stat().st_size:,} bytes)")
        print(f"  • 12 Sheets:")
        print(f"     1. Dashboard")
        print(f"     2. Strategy Rationale (Dark Navy #0D47A1 tab, ELI5 quant rationale, 5-yr proofs)")
        print(f"     3. Sector Rotation (12 sectors, relative alpha, RRG quadrants)")
        print(f"     4. Industry Ranking")
        print(f"     5. Industry History 30d")
        print(f"     6. Stock Ranking (Volar, Delivery %, ATR, TradingView links)")
        print(f"     7. Top Candidates (ATR Risk Parity, Stop Loss, 2-per-sector cap)")
        print(f"     8. Highest Delivery (Institutional accumulation spikes >= 5Cr)")
        print(f"     9. ETF Momentum Ranking (Definedge Momentify ALL-ONE Top 7)")
        print(f"    10. Pick Performance (Vintage performance tracker)")
        print(f"    11. Breadth History")
        print(f"    12. Configuration")
    else:
        print(f"\n{C_RED}✗ Failed to compile Excel workbook.{C_RESET}")

    input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [16]: Interactive Investing Settings TUI
# ═══════════════════════════════════════════════════════════════════════
def run_investing_settings_flow():
    from core.settings import interactive_settings_menu
    interactive_settings_menu(BASE_DIR)


# ═══════════════════════════════════════════════════════════════════════
# Option [17]: Batch Scan All 36 NIFTY Indices (30-Day TTL Reconcile & Master Report)
# ═══════════════════════════════════════════════════════════════════════
def run_all_indices_batch_flow(as_of_date: Optional[str] = None, force_refresh: bool = False, interactive: bool = True):
    clear_screen()
    target_date = as_of_date or get_latest_date()
    print_banner(target_date)
    print(f"\n{C_BOLD}{C_CYAN}🌐 BATCH RECONCILIATION & SCAN FOR ALL 36 NIFTY INDICES{C_RESET}")
    print(f" {C_GRAY}Cache Refresh TTL Policy: 30.0 Days | Target EOD: {target_date}{C_RESET}\n")

    try:
        from scripts.reconcile_and_test_all_universes import main as run_batch_reconcile
        run_batch_reconcile()
    except Exception as e:
        print(f"{C_RED}Error running batch reconciliation: {e}{C_RESET}")

    if interactive:
        input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# Option [18]: Blazing Fast Brute Force Optimizer & Strategy Matrix
# ═══════════════════════════════════════════════════════════════════════
def run_brute_force_flow(
    interactive: bool = True,
    mode: str = "baseline",
    schedule: str = "monthly",
    universe_mode: str = "NIFTY500",
    top_n: int = 20,
    sizing_mode: str = "atr_risk_parity",
    start_date: str = "2016-01-01",
    end_date: str = "2026-08-31",
):
    clear_screen()
    latest_date = get_latest_date()
    print_banner(latest_date)
    print(f"\n{C_BOLD}{C_YELLOW}⚡ BLAZING FAST BRUTE FORCE OPTIMIZER & STRATEGY MATRIX{C_RESET}")
    print(f" {C_GRAY}Architecture: Qualcomm Snapdragon 8 Gen 2 • Native C99 NEON / pthread • S23{C_RESET}\n")

    from brute_force.runner import BruteForceCampaignRunner
    from brute_force.grid import (
        get_canonical_baseline_param,
        generate_tier1_baseline_matrix,
        generate_tier2_ablation_grid,
        generate_tier3_hyperparameter_grid,
        generate_tier4_rolling_windows_grid,
        MACRO_ERAS,
        REBALANCE_SCHEDULES,
    )

    runner = BruteForceCampaignRunner()

    if not interactive:
        print(f"Executing Brute Force in non-interactive mode: mode={mode}, schedule={schedule}, universe={universe_mode}...")
        if mode == "baseline":
            res = runner.run_baseline(start_date=start_date, end_date=end_date, schedule=schedule)
            print(f"\n{C_BOLD}{'=' * 68}{C_RESET}")
            print(f"{C_BOLD} BRUTE FORCE BASELINE SIMULATION REPORT ({schedule.upper()}){C_RESET}")
            print(f"{C_BOLD}{'=' * 68}{C_RESET}")
            for k, v in res.items():
                print(f"  {k:<22}: {v}")
            print(f"{C_BOLD}{'=' * 68}{C_RESET}")
            return res
        elif mode in ("matrix", "full"):
            from scripts.run_optimization_matrix import main as run_matrix_campaign
            return run_matrix_campaign()
        elif mode == "tier1":
            cube = runner.ensure_cube(universe_name=universe_mode)
            grid = generate_tier1_baseline_matrix(cube)
            df = runner.run_sweep(grid)
            print(f"Completed Tier 1 sweep across {len(df)} configurations.")
            return df
        elif mode == "tier2":
            cube = runner.ensure_cube(universe_name=universe_mode)
            grid = generate_tier2_ablation_grid(cube)
            df = runner.run_sweep(grid)
            print(f"Completed Tier 2 ablation sweep across {len(df)} configurations.")
            return df
        elif mode in ("comprehensive", "tier3"):
            cube = runner.ensure_cube(universe_name=universe_mode)
            grid = generate_tier3_hyperparameter_grid(cube, sample_size=10000)
            df = runner.run_sweep(grid)
            print(f"Completed Tier 3 hyperparameter sweep across {len(df)} configurations.")
            return df

    # Interactive Submenu Loop
    while True:
        clear_screen()
        print_banner(latest_date)
        print(f"\n{C_BOLD}{C_YELLOW}⚡ BLAZING FAST BRUTE FORCE OPTIMIZER & STRATEGY MATRIX{C_RESET}")
        print(f" {C_GRAY}Hardware: Qualcomm Snapdragon 8 Gen 2 (8 Cores) • Pure Memory C99 NEON{C_RESET}\n")

        print(f"  {C_GREEN}[ 1]{C_RESET} 🚀  Fast Baseline Simulation (Single run in ~40ms)")
        print(f"  {C_CYAN}[ 2]{C_RESET} 📅  Rebalance Schedules Sweep (Weekly vs Monthly vs Quarterly vs Semi-Annual vs Yearly)")
        print(f"  {C_BLUE}[ 3]{C_RESET} 🏛️   Macro Eras Historical Stress-Test (7 Historical Eras from 2008 to 2026)")
        print(f"  {C_MAGENTA}[ 4]{C_RESET} 🔬  Systematic Strategy Filter Ablation (Leave-One-Out Factor Attribution)")
        print(f"  {C_YELLOW}[ 5]{C_RESET} 🎲  Monte Carlo Rolling Windows & Deflated Sharpe Ratio (DSR Validation)")
        print(f"  {C_WHITE}[ 6]{C_RESET} 🌐  Execute Complete 4-Tier Optimization Matrix Campaign (Reports + Charts)")
        print(f"\n  {C_RED}[ 0]{C_RESET} 🔙  Return to Main Menu\n")

        try:
            sub_choice = input(f"{C_BOLD}Select Brute Force Option [0-6]: {C_RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if sub_choice in ("0", ""):
            break

        elif sub_choice == "1":
            print(f"\n{C_CYAN}── FAST BASELINE SIMULATION ──{C_RESET}")
            sched_in = input(f"  Rebalance Schedule [weekly/monthly/quarterly/half_yearly/yearly] [Default: monthly]: ").strip().lower() or "monthly"
            start_in = input(f"  Start Date (YYYY-MM-DD) [Default: 2016-01-01]: ").strip() or "2016-01-01"
            end_in = input(f"  End Date (YYYY-MM-DD) [Default: 2026-08-31]: ").strip() or "2026-08-31"

            print(f"\n{C_YELLOW}Running native C99 simulation on Snapdragon 8 Gen 2...{C_RESET}")
            res = runner.run_baseline(start_date=start_in, end_date=end_in, schedule=sched_in)

            print(f"\n{C_BOLD}{'=' * 68}{C_RESET}")
            print(f"{C_BOLD} CANONICAL BASELINE PERFORMANCE SUMMARY ({start_in} to {end_in}){C_RESET}")
            print(f"{C_BOLD}{'=' * 68}{C_RESET}")
            print(f"  Schedule:            {C_CYAN}{res['schedule'].upper()}{C_RESET}")
            print(f"  CAGR:                {C_GREEN}{res['cagr_pct']:+.2f}%{C_RESET}")
            print(f"  Sharpe Ratio:        {C_BOLD}{res['sharpe_ratio']:.2f}{C_RESET}")
            print(f"  Sortino Ratio:       {res['sortino_ratio']:.2f}")
            print(f"  Max Drawdown:        {C_RED}{res['max_drawdown_pct']:.2f}%{C_RESET}")
            print(f"  Calmar Ratio:        {res['calmar_ratio']:.2f}")
            print(f"  Total Trades:        {res['total_trades']:,}")
            print(f"  Win Rate:            {res['win_rate_pct']:.1f}%")
            print(f"  Profit Factor:       {res['profit_factor']:.2f}")
            print(f"  Ending Equity:       ₹{res['ending_equity']:,.2f}")
            print(f"  Annual Turnover:     {res['turnover_annual_pct']:.1f}%")
            print(f"  C99 Kernel Latency:  {C_YELLOW}{res['sim_latency_ms']:.2f} ms{C_RESET}")
            print(f"{C_BOLD}{'=' * 68}{C_RESET}")

            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")

        elif sub_choice == "2":
            print(f"\n{C_CYAN}── REBALANCE SCHEDULES COMPARISON SWEEP ──{C_RESET}")
            cube = runner.ensure_cube(universe_name="NIFTY500")
            params = []
            for s_idx, s_name in enumerate(REBALANCE_SCHEDULES):
                p = get_canonical_baseline_param()
                p["param_id"] = s_idx
                p["schedule"] = s_name
                p["schedule_idx"] = s_idx
                p["start_date_idx"] = 0
                p["end_date_idx"] = cube.num_dates - 1
                params.append(p)

            print(f"{C_YELLOW}Executing sweep across all 5 rebalancing schedules (2008-2026)...{C_RESET}")
            df = runner.run_sweep(params, num_threads=8)

            print(f"\n{C_BOLD}{'=' * 78}{C_RESET}")
            print(f"{C_BOLD} SCHEDULE COMPARISON & TURNOVER FRICTION DRAG (2008–2026 FULL HISTORY){C_RESET}")
            print(f"{C_BOLD}{'=' * 78}{C_RESET}")
            print(f"{'Schedule':<14} {'CAGR %':>10} {'Sharpe':>8} {'Max DD %':>10} {'Trades':>8} {'Win Rate':>10} {'Turnover %':>12}")
            print(f"{'─' * 78}")
            for _, r in df.iterrows():
                print(f"{r['schedule'].upper():<14} {r['cagr']:>9.2f}% {r['sharpe']:>8.2f} {r['max_drawdown']:>9.1f}% {int(r['total_trades']):>8} {r['win_rate']:>9.1f}% {r['turnover_annual']:>11.1f}%")
            print(f"{C_BOLD}{'=' * 78}{C_RESET}")

            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")

        elif sub_choice == "3":
            print(f"\n{C_CYAN}── MACRO ERAS HISTORICAL STRESS-TEST (7 ERAS) ──{C_RESET}")
            cube = runner.ensure_cube(universe_name="NIFTY500")
            grid = generate_tier1_baseline_matrix(cube)
            print(f"{C_YELLOW}Executing 35 simulations across 7 Historical Eras x 5 Schedules...{C_RESET}")
            df = runner.run_sweep(grid, num_threads=8)

            df_m = df[df["schedule"] == "monthly"]
            print(f"\n{C_BOLD}{'=' * 82}{C_RESET}")
            print(f"{C_BOLD} HISTORICAL MACRO ERAS PERFORMANCE MATRIX (MONTHLY REBALANCING){C_RESET}")
            print(f"{C_BOLD}{'=' * 82}{C_RESET}")
            print(f"{'Era':<12} {'Description':<32} {'CAGR %':>10} {'Sharpe':>8} {'Max DD %':>10} {'Trades':>8}")
            print(f"{'─' * 82}")
            for _, r in df_m.iterrows():
                desc = str(r['era_description'])[:30]
                print(f"{r['era']:<12} {desc:<32} {r['cagr']:>9.2f}% {r['sharpe']:>8.2f} {r['max_drawdown']:>9.1f}% {int(r['total_trades']):>8}")
            print(f"{C_BOLD}{'=' * 82}{C_RESET}")

            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")

        elif sub_choice == "4":
            print(f"\n{C_CYAN}── SYSTEMATIC STRATEGY FILTER ABLATION (FACTOR ATTRIBUTION) ──{C_RESET}")
            cube = runner.ensure_cube(universe_name="NIFTY500")
            grid = generate_tier2_ablation_grid(cube)
            print(f"{C_YELLOW}Executing 44 filter ablation simulations across Modern & Full history...{C_RESET}")
            df = runner.run_sweep(grid, num_threads=8)

            df_modern = df[(df["era"] == "2016-2026") & (df["schedule"] == "monthly")]
            print(f"\n{C_BOLD}{'=' * 82}{C_RESET}")
            print(f"{C_BOLD} FACTOR ABLATION & ATTRIBUTION TABLE (MODERN ERA 2016–2026){C_RESET}")
            print(f"{C_BOLD}{'=' * 82}{C_RESET}")
            print(f"{'Variant':<22} {'CAGR %':>10} {'Sharpe':>8} {'Max DD %':>10} {'Win Rate':>10} {'Turnover %':>12}")
            print(f"{'─' * 82}")
            for _, r in df_modern.iterrows():
                print(f"{r['ablation_variant']:<22} {r['cagr']:>9.2f}% {r['sharpe']:>8.2f} {r['max_drawdown']:>9.1f}% {r['win_rate']:>9.1f}% {r['turnover_annual']:>11.1f}%")
            print(f"{C_BOLD}{'=' * 82}{C_RESET}")

            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")

        elif sub_choice == "5":
            print(f"\n{C_CYAN}── MONTE CARLO ROLLING WINDOWS & DEFLATED SHARPE RATIO (DSR) ──{C_RESET}")
            cube = runner.ensure_cube(universe_name="NIFTY500")
            grid = generate_tier4_rolling_windows_grid(cube, num_windows=200)
            print(f"{C_YELLOW}Executing {len(grid)} Monte Carlo rolling window simulations (1y to 10y)...{C_RESET}")
            df = runner.run_sweep(grid, num_threads=8)

            sr_c = df[df["tier"] == "TIER_4_ROLLING_CANONICAL"]["sharpe"]
            sr_ng = df[df["tier"] == "TIER_4_ROLLING_NEXTGEN"]["sharpe"]

            print(f"\n{C_BOLD}{'=' * 72}{C_RESET}")
            print(f"{C_BOLD} MONTE CARLO ROLLING WINDOW STATISTICAL SUMMARY{C_RESET}")
            print(f"{C_BOLD}{'=' * 72}{C_RESET}")
            print(f"  Canonical Baseline Mean Sharpe:  {C_GREEN}{sr_c.mean():.3f}{C_RESET} (Median: {sr_c.median():.3f}, Std: {sr_c.std():.3f})")
            print(f"  Next-Gen Upgraded Mean Sharpe:   {C_GREEN}{sr_ng.mean():.3f}{C_RESET} (Median: {sr_ng.median():.3f}, Std: {sr_ng.std():.3f})")
            print(f"  Benchmark (NIFTY 500) Sharpe:    0.450")
            print(f"  Fraction Outperforming Index:    {C_BOLD}{(sr_c > 0.45).mean() * 100:.1f}%{C_RESET}")
            print(f"{C_BOLD}{'=' * 72}{C_RESET}")

            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")

        elif sub_choice == "6":
            print(f"\n{C_CYAN}── EXECUTE COMPLETE 4-TIER OPTIMIZATION MATRIX CAMPAIGN ──{C_RESET}")
            from scripts.run_optimization_matrix import main as run_matrix_campaign
            run_matrix_campaign()
            input(f"\n{C_GRAY}Press Enter to return to menu...{C_RESET}")


# ═══════════════════════════════════════════════════════════════════════
# MAIN MENU (18 Options)
# ═══════════════════════════════════════════════════════════════════════
def main_menu():
    while True:
        clear_screen()
        latest_date = get_latest_date()
        print_banner(latest_date)

        print(f"\n{C_BOLD} ── SCANNER & ANALYSIS ──{C_RESET}")
        print(f"  {C_GREEN}[ 1]{C_RESET} 🚀  Run Weekly Momentum Scanner (Select from 36 Nifty Indices or All)")
        print(f"  {C_YELLOW}[17]{C_RESET} 🌐  Batch Scan All 36 NIFTY Indices (30-Day TTL Reconcile & Master Report)")
        print(f"  {C_CYAN}[10]{C_RESET} 📈  Standalone Market Breadth Report")
        print(f"  {C_MAGENTA}[11]{C_RESET} 🔄  Standalone Sector Rotation & RRG Analysis")
        print(f"  {C_CYAN}[13]{C_RESET} 🎯  Definedge ALL-ONE ETF Momentum Scanner (Top 7)")
        print(f"  {C_GREEN}[14]{C_RESET} 📦  High Delivery Volume Spikes & Accumulation Tracker")
        print(f"  {C_BLUE}[15]{C_RESET} 📑  Regenerate Institutional 12-Sheet Excel Workbook")

        print(f"\n{C_BOLD} ── TELEGRAM ──{C_RESET}")
        print(f"  {C_BLUE}[ 2]{C_RESET} 📱  Preview Telegram Alert (Terminal Preview)")
        print(f"  {C_MAGENTA}[ 3]{C_RESET} ⚡  Dispatch Live Telegram Alert (Text + Charts + 12-Sheet Excel)")

        print(f"\n{C_BOLD} ── PORTFOLIO, BACKTEST & BRUTE FORCE ──{C_RESET}")
        print(f"  {C_GREEN}[ 4]{C_RESET} 📊  Generate Visual Charts & Tearsheets")
        print(f"  {C_CYAN}[ 5]{C_RESET} 💼  Run Lightweight Custom Backtester")
        print(f"  {C_GREEN}[ 7]{C_RESET} 💰  Portfolio Rebalancing & Order Generation")
        print(f"  {C_YELLOW}[18]{C_RESET} ⚡  Blazing Brute Force Optimizer & Strategy Matrix (C99 NEON / Multi-Schedule / Multi-Era)")

        print(f"\n{C_BOLD} ── CONFIGURATION & MANDATE ──{C_RESET}")
        print(f"  {C_WHITE}[16]{C_RESET} ⚙️   Configure Investing & Mandate Settings (TUI Console)")

        print(f"\n{C_BOLD} ── DATA & MAINTENANCE ──{C_RESET}")
        print(f"  {C_MAGENTA}[ 8]{C_RESET} 📡  Auto-Fetch Market Data (NSE Bhavcopy Sync)")
        print(f"  {C_BLUE}[ 9]{C_RESET} 🏭  Sync NSE Sector Taxonomy")
        print(f"  {C_YELLOW}[12]{C_RESET} 🔍  Full Database Integrity Audit")
        print(f"  {C_YELLOW}[ 6]{C_RESET} 🛡️   Run Master Institutional Test Suite (Tests 01-09)")

        print(f"\n  {C_RED}[ 0]{C_RESET} 🚪  Exit Workstation\n")

        try:
            choice = input(f"{C_BOLD}Select Option [0-18]: {C_RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        handlers = {
            "1": run_scanner_flow,
            "2": run_telegram_preview,
            "3": run_telegram_dispatch,
            "4": run_visuals_generator,
            "5": run_custom_backtest_flow,
            "6": run_tdd_suite,
            "7": run_portfolio_orders,
            "8": run_auto_fetch,
            "9": run_sector_sync,
            "10": run_standalone_breadth,
            "11": run_standalone_sector_rrg,
            "12": run_database_audit,
            "13": run_etf_scanner_flow,
            "14": run_delivery_analytics_flow,
            "15": run_excel_regenerator_flow,
            "16": run_investing_settings_flow,
            "17": run_all_indices_batch_flow,
            "18": run_brute_force_flow,
        }

        if choice == "0":
            print(f"\n{C_CYAN}Goodbye! Project MIP Pydroid 3 session ended.{C_RESET}\n")
            break
        elif choice in handlers:
            handlers[choice]()
        else:
            print(f"{C_RED}Invalid option!{C_RESET}")
            time.sleep(1)


def build_parser() -> argparse.ArgumentParser:
    """Builds and returns the CLI argument parser for main.py."""
    parser = argparse.ArgumentParser(description="Project MIP Pydroid 3 Mobile Trading Desk — 36 NIFTY Universes Edition")
    parser.add_argument("--option", type=int, choices=range(1, 19),
                        help="Run option directly without menu (1-18)")
    parser.add_argument("--universe", type=str, default="NIFTY500",
                        help="Target universe selection (any of 36 NIFTY indices, e.g. NIFTY500, NIFTY750, NIFTYBank, NIFTYIT, ALL)")
    parser.add_argument("--date", type=str, default=None,
                        help="Target evaluation session date (YYYY-MM-DD)")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Force live constituent download from niftyindices.com bypassing 30-day cache TTL")
    parser.add_argument("--scan-all-universes", action="store_true",
                        help="Execute batch scan and reconciliation across all 36 NIFTY universes")
    parser.add_argument("--brute-force", action="store_true",
                        help="Execute blazing brute force engine directly (Option 18)")
    parser.add_argument("--brute-force-mode", type=str, choices=["baseline", "tier1", "tier2", "comprehensive", "matrix"], default="baseline",
                        help="Brute force execution mode (default baseline)")
    parser.add_argument("--schedule", type=str, choices=["weekly", "monthly", "quarterly", "half_yearly", "yearly"], default="monthly",
                        help="Rebalance schedule frequency (default monthly)")
    parser.add_argument("--top-n", type=int, default=20,
                        help="Portfolio Top N stocks (default 20)")
    parser.add_argument("--sizing-mode", type=str, choices=["atr_risk_parity", "equal_weight"], default="atr_risk_parity",
                        help="Position sizing mode (default atr_risk_parity)")
    parser.add_argument("--allow-stale", action="store_true",
                        help="Allow execution on latest available database date if recent market data is not yet synced")
    parser.add_argument("--no-auto-sync", action="store_true",
                        help="Disable automated market data synchronization before scan")
    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()

    if args.scan_all_universes:
        run_all_indices_batch_flow(as_of_date=args.date, force_refresh=args.force_refresh, interactive=False)
        sys.exit(0)

    if args.brute_force:
        run_brute_force_flow(
            interactive=False,
            mode=args.brute_force_mode,
            schedule=args.schedule,
            universe_mode=args.universe,
            top_n=args.top_n,
            sizing_mode=args.sizing_mode,
            start_date=args.date or "2016-01-01",
        )
        sys.exit(0)

    option_map = {
        1: lambda: run_scanner_flow(
            interactive=False,
            universe_mode=args.universe,
            as_of_date=args.date,
            force_refresh=args.force_refresh,
            allow_stale=args.allow_stale,
            auto_sync=(not args.no_auto_sync),
        ),
        2: run_telegram_preview,
        3: run_telegram_dispatch,
        4: run_visuals_generator,
        5: run_custom_backtest_flow,
        6: run_tdd_suite,
        7: run_portfolio_orders,
        8: run_auto_fetch,
        9: run_sector_sync,
        10: run_standalone_breadth,
        11: run_standalone_sector_rrg,
        12: run_database_audit,
        13: run_etf_scanner_flow,
        14: run_delivery_analytics_flow,
        15: run_excel_regenerator_flow,
        16: run_investing_settings_flow,
        17: lambda: run_all_indices_batch_flow(as_of_date=args.date, force_refresh=args.force_refresh, interactive=False),
        18: lambda: run_brute_force_flow(
            interactive=False,
            mode=args.brute_force_mode,
            schedule=args.schedule,
            universe_mode=args.universe,
            top_n=args.top_n,
            sizing_mode=args.sizing_mode,
            start_date=args.date or "2016-01-01",
        ),
    }

    if args.option and args.option in option_map:
        lock_file = BASE_DIR / "reports" / ".scanner.lock"
        if args.option in (1, 17):
            try:
                (BASE_DIR / "reports").mkdir(parents=True, exist_ok=True)
                fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                os.close(fd)
            except FileExistsError:
                print(f"{C_RED}Error: Another scanner process is already running (lock: {lock_file}){C_RESET}")
                sys.exit(1)
        try:
            option_map[args.option]()
        finally:
            if args.option in (1, 17) and lock_file.exists():
                try:
                    lock_file.unlink()
                except OSError:
                    pass
    else:
        main_menu()


