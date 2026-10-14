"""
Project MIP Pydroid 3: Interactive Investing & Portfolio Settings Manager
Directive: DIR-PROD-PYDROID3-SETTINGS-01

Provides centralized, persistent configuration for:
  - Capital allocation & portfolio size (Top N)
  - Sector concentration hard caps (Max per sector)
  - Position sizing modes (ATR Risk Parity vs Equal Weight)
  - Risk budget & Trailing Stop Loss (ATR multiplier)
  - Exit buffer ranking cutoff
  - Target universe selection (Nifty 500 / 750 / All)
  - Market regime filter & Friction stress tier
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional

from .data_engine import get_base_dir

# ANSI Styling
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_GREEN = "\033[92m"
C_RED = "\033[91m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"
C_GRAY = "\033[90m"
C_WHITE = "\033[97m"

DEFAULT_INVESTING_SETTINGS: Dict[str, Any] = {
    "capital": 1000000.0,            # INR 10,00,000 (10 Lakhs)
    "top_n": 20,                     # 20 holdings
    "max_per_sector": 2,             # Hard cap: Max 2 scrips per sector
    "sizing_mode": "atr_risk_parity",# "atr_risk_parity" or "equal_weight"
    "risk_per_trade_pct": 1.0,       # 1.0% risk per position
    "atr_stop_multiplier": 2.0,      # Stop Loss = 2.0x ATR-14
    "exit_buffer_multiplier": 2.0,   # Exit Buffer = 2.0x Top-N (Rank 40)
    "cash_buffer_pct": 0.0,          # 0% cash buffer reserved
    "universe_mode": "NIFTY500",      # "NIFTY500", "NIFTY750", "ALL"
    "regime_filter_active": True,    # Filter on benchmark 20 EMA
    "friction_multiplier": 1.0,      # 1.0x institutional costs
}

SETTINGS_FILE_NAME = "investing_settings.json"


def get_settings_path(base_dir: Optional[Path] = None) -> Path:
    b = Path(base_dir) if base_dir else get_base_dir()
    d = b / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d / SETTINGS_FILE_NAME


def load_investing_settings(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Loads saved settings from JSON with default fallback."""
    spath = get_settings_path(base_dir)
    settings = dict(DEFAULT_INVESTING_SETTINGS)
    if spath.exists():
        try:
            with open(spath, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                settings.update(loaded)
        except Exception as e:
            print(f"{C_YELLOW}⚠ Warning: Could not read settings file ({e}). Using defaults.{C_RESET}")
    return settings


def save_investing_settings(settings: Dict[str, Any], base_dir: Optional[Path] = None) -> bool:
    """Saves settings atomically to JSON file."""
    spath = get_settings_path(base_dir)
    try:
        tmp_path = spath.with_suffix(".tmp.json")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, sort_keys=True)
        tmp_path.replace(spath)
        return True
    except Exception as e:
        print(f"{C_RED}❌ Error saving settings: {e}{C_RESET}")
        return False


def format_settings_summary(settings: Dict[str, Any]) -> str:
    """Formats settings as a clean tabular dashboard."""
    cap = float(settings.get("capital", 1000000.0))
    top_n = int(settings.get("top_n", 20))
    max_sec = int(settings.get("max_per_sector", 2))
    mode = str(settings.get("sizing_mode", "atr_risk_parity"))
    mode_str = "ATR-14 Risk Parity (1% Risk Budget)" if mode == "atr_risk_parity" else "Equal Weight (1/N)"
    risk_pct = float(settings.get("risk_per_trade_pct", 1.0))
    atr_mult = float(settings.get("atr_stop_multiplier", 2.0))
    exit_mult = float(settings.get("exit_buffer_multiplier", 2.0))
    exit_rank = int(top_n * exit_mult)
    cash_buf = float(settings.get("cash_buffer_pct", 0.0))
    u_mode = str(settings.get("universe_mode", "NIFTY500")).upper()
    u_str = "NIFTY 500 (Large/Mid/Small)" if "500" in u_mode else ("NIFTY 750 (Total Market)" if "750" in u_mode else "ALL ACTIVE SCRIPS")
    regime = bool(settings.get("regime_filter_active", True))
    fric = float(settings.get("friction_multiplier", 1.0))

    lines = [
        f"{C_BOLD}{C_CYAN}╔══════════════════════════════════════════════════════════════════════╗{C_RESET}",
        f"{C_BOLD}{C_CYAN}║            PROJECT MIP — CURRENT INVESTING & MANDATE SETTINGS        ║{C_RESET}",
        f"{C_BOLD}{C_CYAN}╚══════════════════════════════════════════════════════════════════════╝{C_RESET}",
        f"  {C_BOLD}[1] Target Capital:{C_RESET}          ₹{cap:,.2f} ({cap/100000:.1f} Lakhs)",
        f"  {C_BOLD}[2] Portfolio Capacity:{C_RESET}      Top {top_n} Stocks",
        f"  {C_BOLD}[3] Sector Hard Cap:{C_RESET}         Max {max_sec} Stocks per Sector",
        f"  {C_BOLD}[4] Position Sizing Mode:{C_RESET}   {mode_str}",
        f"  {C_BOLD}[5] Risk Budget Per Scrip:{C_RESET} {risk_pct:.1f}% of Capital",
        f"  {C_BOLD}[6] Trailing Stop Loss:{C_RESET}     {atr_mult:.1f}x ATR-14",
        f"  {C_BOLD}[7] Exit Buffer Cutoff:{C_RESET}     Rank {exit_rank} ({exit_mult:.1f}x Top-N)",
        f"  {C_BOLD}[8] Cash Reserve Buffer:{C_RESET}    {cash_buf:.1f}%",
        f"  {C_BOLD}[9] Target Universe:{C_RESET}        {u_str}",
        f"  {C_BOLD}[10] Market Regime Filter:{C_RESET}  {'🟢 ACTIVE (Benchmark 20 EMA)' if regime else '🔴 DISABLED (Always Invested)'}",
        f"  {C_BOLD}[11] Friction Stress Tier:{C_RESET}  {fric:.1f}x Institutional Tariff",
        f"{C_GRAY}────────────────────────────────────────────────────────────────────────{C_RESET}",
    ]
    return "\n".join(lines)


def interactive_settings_menu(base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Interactive TUI configuration console for investing parameters."""
    settings = load_investing_settings(base_dir)

    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print(format_settings_summary(settings))
        print(f"\n{C_BOLD}SELECT PARAMETER TO MODIFY:{C_RESET}")
        print(f"  {C_GREEN}[1-11]{C_RESET} Edit Specific Parameter")
        print(f"  {C_YELLOW}[R]{C_RESET}    Reset to Default Institutional Settings")
        print(f"  {C_CYAN}[S]{C_RESET}    Save Settings & Return to Main Desk")
        print(f"  {C_RED}[Q]{C_RESET}    Cancel & Discard Changes")

        choice = input(f"\n{C_BOLD}Enter Choice [1-11, R, S, Q]: {C_RESET}").strip().upper()

        if choice == "Q":
            print(f"{C_YELLOW}Settings changes discarded.{C_RESET}")
            break
        elif choice == "S":
            if save_investing_settings(settings, base_dir):
                print(f"\n{C_GREEN}✓ Investing settings saved successfully to data/{SETTINGS_FILE_NAME}!{C_RESET}")
            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")
            break
        elif choice == "R":
            settings = dict(DEFAULT_INVESTING_SETTINGS)
            print(f"\n{C_YELLOW}Settings reset to institutional defaults.{C_RESET}")
            input(f"\n{C_GRAY}Press Enter to continue...{C_RESET}")
        elif choice == "1":
            val = input(f"Enter Target Capital in INR [Current: ₹{settings['capital']:,.0f}]: ").strip()
            if val:
                try:
                    c = float(val.replace(",", "").replace("₹", ""))
                    if c > 0:
                        settings["capital"] = c
                except ValueError:
                    print(f"{C_RED}Invalid numeric capital amount!{C_RESET}")
                    input("Press Enter...")
        elif choice == "2":
            val = input(f"Enter Portfolio Size (Top N holdings) [Current: {settings['top_n']}]: ").strip()
            if val:
                try:
                    n = int(val)
                    if 1 <= n <= 100:
                        settings["top_n"] = n
                except ValueError:
                    print(f"{C_RED}Invalid integer!{C_RESET}")
                    input("Press Enter...")
        elif choice == "3":
            val = input(f"Enter Sector Concentration Cap (Max stocks per sector) [Current: {settings['max_per_sector']}]: ").strip()
            if val:
                try:
                    m = int(val)
                    if 1 <= m <= 20:
                        settings["max_per_sector"] = m
                except ValueError:
                    print(f"{C_RED}Invalid integer!{C_RESET}")
                    input("Press Enter...")
        elif choice == "4":
            print("\nSelect Position Sizing Mode:")
            print("  [1] ATR-14 Volatility Risk Parity (1% Risk Budget per trade)")
            print("  [2] Equal-Weight Capital Allocation (1 / N)")
            c_mode = input("Select [1-2]: ").strip()
            if c_mode == "1":
                settings["sizing_mode"] = "atr_risk_parity"
            elif c_mode == "2":
                settings["sizing_mode"] = "equal_weight"
        elif choice == "5":
            val = input(f"Enter Risk Budget Per Position (%) [Current: {settings['risk_per_trade_pct']}%]: ").strip()
            if val:
                try:
                    r = float(val)
                    if 0.1 <= r <= 20.0:
                        settings["risk_per_trade_pct"] = r
                except ValueError:
                    print(f"{C_RED}Invalid percentage!{C_RESET}")
                    input("Press Enter...")
        elif choice == "6":
            val = input(f"Enter Stop Loss Multiplier (x ATR-14) [Current: {settings['atr_stop_multiplier']}x]: ").strip()
            if val:
                try:
                    mult = float(val)
                    if 0.5 <= mult <= 10.0:
                        settings["atr_stop_multiplier"] = mult
                except ValueError:
                    print(f"{C_RED}Invalid multiplier!{C_RESET}")
                    input("Press Enter...")
        elif choice == "7":
            val = input(f"Enter Exit Buffer Multiplier (e.g. 2.0 = 2x Top-N) [Current: {settings['exit_buffer_multiplier']}x]: ").strip()
            if val:
                try:
                    buf = float(val)
                    if 1.0 <= buf <= 5.0:
                        settings["exit_buffer_multiplier"] = buf
                except ValueError:
                    print(f"{C_RED}Invalid multiplier!{C_RESET}")
                    input("Press Enter...")
        elif choice == "8":
            val = input(f"Enter Cash Reserve Buffer (%) [Current: {settings['cash_buffer_pct']}%]: ").strip()
            if val:
                try:
                    cb = float(val)
                    if 0.0 <= cb <= 50.0:
                        settings["cash_buffer_pct"] = cb
                except ValueError:
                    print(f"{C_RED}Invalid cash buffer!{C_RESET}")
                    input("Press Enter...")
        elif choice == "9":
            print("\nSelect Default Universe:")
            print("  [1] NIFTY 500 (Large, Mid & Smallcap — ~500 Stocks)")
            print("  [2] NIFTY 750 (Total Market: 500 + Microcap 250 — ~750 Stocks)")
            print("  [3] ALL ACTIVE SCRIPS (Full Point-In-Time Database — ~988 Stocks)")
            c_u = input("Select Universe [1-3]: ").strip()
            if c_u == "1":
                settings["universe_mode"] = "NIFTY500"
            elif c_u == "2":
                settings["universe_mode"] = "NIFTY750"
            elif c_u == "3":
                settings["universe_mode"] = "ALL"
        elif choice == "10":
            val = input("Enable Market Regime Filter? (Pause entries if Benchmark < 20 EMA) [Y/N]: ").strip().upper()
            if val in ["Y", "YES", "1", "TRUE"]:
                settings["regime_filter_active"] = True
            elif val in ["N", "NO", "0", "FALSE"]:
                settings["regime_filter_active"] = False
        elif choice == "11":
            print("\nSelect Friction Stress Tier:")
            print("  [1] 1.0x Real Institutional Tariff (STT, Stamp, GST, 10 bps slippage)")
            print("  [2] 2.0x Stress Test Tariff")
            print("  [3] 3.0x Extreme Friction Tariff")
            c_f = input("Select [1-3]: ").strip()
            if c_f in ["1", "2", "3"]:
                settings["friction_multiplier"] = float(c_f)

    return settings
