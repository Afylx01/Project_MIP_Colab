"""
scripts/dispatch_institutional_pipeline.py - Single-Entry Institutional Pipeline Dispatcher
Project MIP Institutional Edition (AQR / Aladdin Automated Production Standard)

Orchestrates end-to-end institutional workflow:
1. Pre-Flight Operational Health & Database Verification
2. Hardened Momentum Scanner with Dynamic Reference Benchmark
3. Institutional Tail Risk & Factor Regression Analytics
4. Microstructure Liquidity Profiling & Capacity Modeling
5. Pre-Trade Regulatory & SEBI Concentration Audit
6. Standalone Publication-Grade Interactive HTML Tearsheet
7. Institutional Deliverables Packaging (.zip)
"""

from __future__ import annotations

import os
import sys
import time
import argparse
import logging
import numpy as np
import pandas as pd
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import get_latest_date, get_expected_latest_eod
from scripts.health_check import OperationalHealthChecker
from scripts.scanner_hardening import HardenedScanner
from analytics.institutional_risk import calculate_comprehensive_risk_suite
from analytics.liquidity_analytics import compute_liquidity_profile
from compliance.pretrade_audit import PreTradeComplianceAuditor
from reporting.interactive_tearsheet import InstitutionalTearsheetGenerator
from reporting.deliverables_bundle import package_institutional_bundle


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project MIP Single-Entry Institutional Pipeline Dispatcher"
    )
    parser.add_argument("--universe", type=str, default="NIFTY750", help="Target universe (NIFTY750, NIFTY500, ALL, NIFTY50, NIFTYBANK, NIFTYIT)")
    parser.add_argument("--benchmark", type=str, default="NIFTY50", help="Reference benchmark (NIFTY50, NIFTY500, NIFTYBANK, etc.)")
    parser.add_argument("--top-n", type=int, default=10, help="Number of actionable candidate buys (default: 10)")
    parser.add_argument("--date", "--as-of-date", dest="as_of_date", type=str, default=None, help="As-of market date (YYYY-MM-DD)")
    parser.add_argument("--allow-stale", action="store_true", default=False, help="Allow scanning latest available SQLite date")
    parser.add_argument("--use-vol-targeting", action="store_true", default=False, help="Enable EWMA volatility targeting")
    parser.add_argument("--use-delivery-veto", action="store_true", default=True, help="Enable NSE delivery flow absorption veto")
    parser.add_argument("--use-residual-momentum", action="store_true", default=True, help="Enable Blitz et al. (2011) residual momentum")
    parser.add_argument("--export-bundle", action="store_true", default=True, help="Package deliverables into timestamped ZIP")
    return parser


def run_institutional_pipeline(args: argparse.Namespace) -> int:
    start_time = time.time()
    universe = getattr(args, "universe", "NIFTY750")
    benchmark = getattr(args, "benchmark", "NIFTY50")
    top_n = getattr(args, "top_n", 10)
    use_residual_mom = getattr(args, "use_residual_momentum", True)
    use_delivery_veto = getattr(args, "use_delivery_veto", True)
    use_vol_targeting = getattr(args, "use_vol_targeting", False)

    print("=" * 76)
    print("🚀 DISPATCHING INSTITUTIONAL QUANTITATIVE PIPELINE [Project MIP Colab]")
    print(f"  • Universe:          {universe} | Benchmark: {benchmark}")
    print(f"  • Portfolio Size:    Top {top_n} | Risk Sizing: ATR-14 Volatility Parity")
    print(f"  • Alpha Overlays:    ResidualMom={use_residual_mom} | DeliveryVeto={use_delivery_veto} | VolTarget={use_vol_targeting}")
    print("=" * 76)

    # 1. Pre-Flight Health Check
    print("\n[Stage 1/6] Running Pre-Flight Operational Health Check...")
    checker = OperationalHealthChecker(base_dir=PROJECT_ROOT)
    healthy, health = checker.run_all_checks()
    print(f"  ✓ Operational Health: {health.get('overall_health')} ({health.get('checks_passed')}/{health.get('checks_total')} checks passed)")
    if not healthy and not getattr(args, "force", False):
        print(f"❌ Pre-flight health check FAILED ({health.get('checks_passed')}/{health.get('checks_total')} checks passed). Pipeline aborted.")
        sys.exit(1)

    # 2. Resolve Target Date
    target_date = getattr(args, "as_of_date", None) or get_latest_date()
    print(f"  ✓ Resolved Target Session: {target_date}")

    # 3. Execute Hardened Scanner
    print(f"\n[Stage 2/6] Executing Momentum Scanner on {universe} vs {benchmark}...")
    scanner = HardenedScanner(base_dir=PROJECT_ROOT)
    scan_res = scanner.run_scan(
        as_of_date=target_date,
        universe_mode=universe,
        top_n=top_n,
        benchmark=benchmark,
        export_csv=True,
        export_excel=True,
        allow_stale_data=getattr(args, "allow_stale", False),
        use_vol_targeting=use_vol_targeting,
        use_delivery_veto=use_delivery_veto,
        use_residual_momentum=use_residual_mom,
    )
    if isinstance(scan_res, tuple):
        top_df = scan_res[0]
    else:
        top_df = scan_res

    candidate_count = len(top_df) if top_df is not None else 0
    print(f"  ✓ Momentum Filter completed: {candidate_count} candidates selected.")

    # 4. Institutional Risk & Tail Analytics
    print("\n[Stage 3/6] Computing Institutional Tail Risk & Factor Decomposition...")
    sample_returns = []
    benchmark_returns = None
    conn = None
    try:
        import sqlite3
        db_path = PROJECT_ROOT / "data" / "universe.db"
        if db_path.exists() and top_df is not None and not top_df.empty:
            symbols = top_df["symbol"].dropna().tolist()[:10]
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            placeholders = ",".join(["?"] * len(symbols))
            query = f"""
                SELECT symbol, date, close
                FROM prices
                WHERE symbol IN ({placeholders}) AND date <= ? AND close > 0
                ORDER BY date ASC
            """
            df_raw = pd.read_sql_query(query, conn, params=(*symbols, target_date))
            if not df_raw.empty:
                # Drop symbols whose last observation is older than target session
                max_date_in_raw = df_raw["date"].max()
                latest_by_symbol = df_raw.groupby("symbol")["date"].max()
                stale_symbols = set(latest_by_symbol[latest_by_symbol < max_date_in_raw].index)
                if stale_symbols:
                    df_raw = df_raw[~df_raw["symbol"].isin(stale_symbols)]

                if not df_raw.empty:
                    # Pivot WITHOUT ffill to avoid synthesizing zero returns on halted/stale symbols
                    df_pivot = df_raw.pivot(index="date", columns="symbol", values="close")
                    df_pivot = df_pivot.iloc[-253:]
                    min_symbols = max(1, int(len(symbols) * 0.5))
                    valid_counts = df_pivot.notna().sum(axis=1)
                    pct_df = df_pivot.pct_change()
                    pct_df = pct_df[valid_counts >= min_symbols]
                    sample_returns = pct_df.mean(axis=1).dropna().tolist()

        # Try to resolve benchmark returns aligned with sample dates
        try:
            from core.benchmark_validator import resolve_benchmark_dataframe
            bm_df = resolve_benchmark_dataframe(benchmark, base_dir=PROJECT_ROOT)
            if bm_df is not None and not bm_df.empty and "close" in bm_df.columns:
                bm_df["date"] = bm_df["date"].astype(str)
                benchmark_returns = bm_df.set_index("date")["close"].pct_change().dropna()
        except Exception:
            benchmark_returns = None
    except (sqlite3.Error, OSError, ValueError, pd.errors.DataError) as e:
        print(f"  [Warning] Could not extract empirical portfolio returns: {e}")
        sample_returns = []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    risk_metrics = {"scenario_type": "UNAVAILABLE"}
    if sample_returns and len(sample_returns) >= 20:
        try:
            risk_metrics = calculate_comprehensive_risk_suite(
                returns=sample_returns,
                benchmark_returns=benchmark_returns,
                rf_rate=0.065,
            )
            risk_metrics["scenario_type"] = "EMPIRICAL_HISTORICAL_HINDSIGHT_SELECTED"
            var_val = risk_metrics.get("var_95")
            cvar_val = risk_metrics.get("cvar_95")
            ulcer_val = risk_metrics.get("ulcer_index")
            var_str = f"{var_val * 100:.2f}%" if var_val is not None else "N/A"
            cvar_str = f"{cvar_val * 100:.2f}%" if cvar_val is not None else "N/A"
            print(f"  ✓ Tail Risk: [EMPIRICAL] Hist VaR-95 = {var_str} | CVaR-95 = {cvar_str} | Ulcer = {ulcer_val}")
        except Exception as e:
            print(f"  ⚠️ [Warning] calculate_comprehensive_risk_suite failed: {e} — failing closed to UNAVAILABLE.")
            risk_metrics = {"scenario_type": "UNAVAILABLE"}
    else:
        print("  ⚠️ [Warning] Insufficient empirical history for tail risk analytics — marked UNAVAILABLE.")

    # 5. Liquidity Profiling & Capacity Modeling
    print("\n[Stage 4/6] Profiling Order Liquidity & Capacity...")
    liq_profile = compute_liquidity_profile(
        orders_df=top_df,
        capital_inr=1_000_000.0,
    )
    print(f"  ✓ Liquidity: Portfolio DL = {liq_profile.get('portfolio_days_to_liquidate')}d | ADV Part = {liq_profile.get('weighted_adv_participation_pct')}% | Capacity = ₹{liq_profile.get('strategy_capacity_crores')} Cr")

    # 6. Pre-Trade Regulatory & Compliance Audit
    print("\n[Stage 5/6] Verifying SEBI Pre-Trade Compliance & Audit Manifest...")
    auditor = PreTradeComplianceAuditor(base_dir=PROJECT_ROOT)
    compliance = auditor.verify_pretrade_compliance(
        candidates_df=top_df,
        as_of_date=target_date,
        total_portfolio_nav=1_000_000.0,
        available_cash=1_000_000.0,
    )
    print(f"  ✓ Compliance Audit: Status = {compliance.overall_status} (Seal: {compliance.sha256_seal[:16]}...)")

    # 7. Generate Standalone HTML Tearsheet
    print("\n[Stage 6/6] Generating Publication-Grade Interactive HTML Tearsheet...")
    html_path = InstitutionalTearsheetGenerator.generate_html_tearsheet(
        candidates_df=top_df,
        risk_metrics=risk_metrics,
        compliance_manifest=compliance.to_dict(),
        universe=universe,
        benchmark=benchmark,
        as_of_date=target_date,
        output_path=PROJECT_ROOT / "reports" / f"MIP_Institutional_Tearsheet_{target_date}_{universe}.html",
    )
    print(f"  ✓ Interactive Tearsheet: {html_path}")

    # Package Deliverables Bundle
    bundle_path = None
    if getattr(args, "export_bundle", True):
        bundle_path = package_institutional_bundle(
            as_of_date=target_date,
            universe=universe,
            base_dir=PROJECT_ROOT,
        )
        if bundle_path and bundle_path.exists():
            print(f"  ✓ Deliverables Bundle:   {bundle_path} ({bundle_path.stat().st_size:,} bytes)")

    elapsed = time.time() - start_time
    is_unavailable = risk_metrics.get("scenario_type") == "UNAVAILABLE"

    # Enforce fail-closed policy on stale benchmark or blocked scanner health
    is_scan_blocked = False
    allow_stale_data = getattr(args, "allow_stale", False)
    if hasattr(scanner, "last_scan_quality") and isinstance(scanner.last_scan_quality, dict):
        health_state = scanner.last_scan_quality.get("health", {}).get("state")
        bm_regime = scanner.last_scan_quality.get("benchmark_regime", {}) or {}
        bm_status = bm_regime.get("status")
        if health_state == "BLOCKED" and not allow_stale_data:
            is_scan_blocked = True
            print("  ❌ [BLOCKED] Scanner health state is BLOCKED and allow_stale is False.")
        elif bm_status == "STALE" and not allow_stale_data:
            is_scan_blocked = True
            print("  ❌ [BLOCKED] Benchmark status is STALE and allow_stale is False.")

    if is_unavailable:
        status_label = "COMPLETED_WITH_WARNINGS (RISK METRICS UNAVAILABLE)"
    elif is_scan_blocked:
        status_label = "BLOCKED (STALE BENCHMARK / HEALTH FAILURE)"
    else:
        status_label = "COMPLETED"

    exit_code = 1 if (is_unavailable or is_scan_blocked) else 0

    print("\n" + "=" * 76)
    print(f"🏁 INSTITUTIONAL PIPELINE {status_label} IN {elapsed:.2f}s (Exit Code: {exit_code})")
    print(f"  • Reports:     reports/MIP1_Momentum_Scanner_{target_date}_{universe}.xlsx")
    print(f"  • Tearsheet:   {html_path}")
    if bundle_path:
        print(f"  • Bundle Archive: {bundle_path}")
    print("=" * 76)
    return exit_code


def main():
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_institutional_pipeline(args))


if __name__ == "__main__":
    main()
