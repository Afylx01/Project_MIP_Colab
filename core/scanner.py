"""
Project MIP Pydroid 3: Production Momentum Scanner
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Full Parity & Phase 4 Hardened Architecture)

Evaluates verified institutional 5-tier momentum strategy rules on SQLite universe:
  1. Filter 1 (Retracement): Close >= 0.80 * 252d High.
  2. Filter 2 (Trend): Close > 200 EMA.
  3. Filter 3 (Relative Strength): Stock / NIFTY 500 ratio > 200 EMA of ratio.
  4. Ranking Metric: Volar Score = Return_252 / max(vol_252, 0.05).
  5. Market Regime: NIFTY 500 Close vs 20 EMA (Normal vs Defensive).
  6. Sector Concentration Hard Cap: Max 2 stocks per industry/sector (anti-clustering).
  7. ATR-14 Volatility Risk Parity Sizing & 2x ATR dynamic stop loss.
  8. Integrated Definedge Momentify ALL-ONE ETF Engine & NSE Delivery Manager.
  9. Automatic 14-Sheet Institutional Excel Workbook Generation (openpyxl).
 10. Phase 4 Hardening: Full bar validation, anti-IPO 252d minimum, 3-tier deterministic ranking,
     diagnostic reason codes, and health governance state machine.
"""

from collections import Counter
import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Set, Tuple, Any
import numpy as np
import pandas as pd

from .data_engine import (
    get_base_dir,
    get_connection,
    get_latest_date,
    load_bars,
    load_symbol_sector_map,
    load_universe_constituents,
    load_trading_calendar,
    load_authoritative_trading_calendar,
    get_universe_label,
    get_expected_latest_eod,
    resolve_latest_valid_eod,
    StaleDataError,
    DataUnavailableError,
)
from .rrg import compute_rrg_metrics
from .breadth import MarketBreadthEngine
from .sector_rotation import SectorRotationEngine
from .delivery import NSEDeliveryManager
from .etf_engine import ETFMomentumEngine
from .excel_generator import InstitutionalExcelGenerator
from .config import MIPScannerConfig
from .reason_codes import ScannerReasonCode, ScannerReasonCategory
from .validation import ScannerDataValidator, ValidationResult
from .identity import SecurityIdentityManager
from .anomaly import ScannerAnomalyDetector
from .health import ScannerHealthMonitor, ScannerHealthReport, ScannerHealthState
from .scan_quality_report import ScanQualityReporter, CandidateExplanation


def _calc_calendar_aligned_return(s: pd.Series, calendar: Optional[List[str]] = None, lookback: int = 252) -> pd.Series:
    """
    Computes lookback return aligned to trading calendar or bounded index.
    Prevents division by zero or NaN propagation.
    """
    lb = min(len(s), lookback)
    shifted = s.shift(lb).fillna(s.iloc[0])
    denom = shifted.replace(0.0, np.nan)
    return (s / denom - 1.0).fillna(0.0)


class PydroidScanner:
    """Institutional momentum screener with full MIP-1 v5.5.1 parity and Phase 4 hardening."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        config: Optional[MIPScannerConfig] = None,
        benchmark: str = "NIFTY500",
    ):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.benchmark_name = benchmark or "NIFTY500"
        self.config = config or MIPScannerConfig()
        self.config.validate()
        self.benchmark_csv = self.base_dir / "data" / "benchmark_nifty500.csv"
        self.sector_map = load_symbol_sector_map()
        self.breadth_engine = MarketBreadthEngine(self.base_dir)
        self.sector_engine = SectorRotationEngine(self.base_dir)
        self.delivery_manager = NSEDeliveryManager(self.base_dir / "data" / "bhavcopy_delivery")
        self.etf_engine = ETFMomentumEngine(self.base_dir)
        self.excel_generator = InstitutionalExcelGenerator(self.base_dir)

        # Institutional Governance & Quality Engines
        try:
            calendar = load_authoritative_trading_calendar()
        except Exception:
            calendar = None
        self.trading_calendar = calendar or []
        self.validator = ScannerDataValidator(self.config, self.trading_calendar)
        self.identity_mgr = SecurityIdentityManager()
        try:
            from .data_engine import load_applied_corporate_actions
            known_ca = load_applied_corporate_actions()
        except Exception:
            known_ca = []
        self.anomaly_detector = ScannerAnomalyDetector(self.config, known_corporate_actions=known_ca)
        from .analytical_price import AnalyticalPriceEngine
        self.analytical_engine = AnalyticalPriceEngine(self.base_dir / "data" / "corporate_actions_registry.json")
        self.health_monitor = ScannerHealthMonitor(self.config)
        self.quality_reporter = ScanQualityReporter(self.config)
        self.last_health_report: Optional[ScannerHealthReport] = None
        self.last_scan_quality: Optional[Dict[str, Any]] = None

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] [Scanner] {msg}")

    def load_benchmark(self, benchmark_override: Optional[str] = None) -> pd.DataFrame:
        try:
            from core.benchmark_validator import resolve_benchmark_dataframe
            bm_name = benchmark_override or getattr(self, "benchmark_name", "NIFTY500")
            return resolve_benchmark_dataframe(bm_name, base_dir=self.base_dir)
        except Exception:
            if not self.benchmark_csv.exists():
                return pd.DataFrame(columns=["date", "close", "ema_20"])
            df = pd.read_csv(self.benchmark_csv)
            df["date"] = df["date"].astype(str)
            return df

    def evaluate_regime(self, as_of_date: str, benchmark_override: Optional[str] = None) -> Dict:
        """Evaluates benchmark regime against 20 EMA using institutional fail-closed validator."""
        from .benchmark_validator import evaluate_regime as eval_regime
        try:
            calendar = load_authoritative_trading_calendar()
        except Exception:
            calendar = None

        bm_df = self.load_benchmark(benchmark_override=benchmark_override)
        res = eval_regime(
            as_of_date=as_of_date,
            benchmark_csv_or_df=bm_df,
            trading_calendar=calendar,
        )
        res_dict = res.to_dict()
        res_dict["benchmark_name"] = benchmark_override or getattr(self, "benchmark_name", "NIFTY500")
        return res_dict

    def _record_picks_history(self, target_date: str, top_df: pd.DataFrame, market_bullish: bool):
        """Records weekly picks into SQLite picks_history table for Pick Performance tracking."""
        if os.environ.get("MIP_READONLY", "0") == "1":
            return
        conn = None
        try:
            from .data_engine import get_operational_connection
            conn = get_operational_connection()
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS picks_history (
                    pick_date TEXT,
                    symbol TEXT,
                    rank INTEGER,
                    industry TEXT,
                    regime TEXT,
                    signal_type TEXT,
                    status TEXT,
                    entry_price REAL,
                    ret_1w REAL,
                    ret_1m REAL,
                    ret_since REAL,
                    last_px_date TEXT,
                    volar_score REAL,
                    PRIMARY KEY (pick_date, symbol)
                )
            """)
            regime_str = "BULL" if market_bullish else "BEAR"
            sig_str = "BUY" if market_bullish else "BEAR_HOLD"
            for _, r in top_df.iterrows():
                sym = str(r["symbol"]).strip().upper()
                rnk = int(r.get("rank", 0))
                ind = str(r.get("industry", r.get("sector", "SERVICES"))).strip().upper()
                px = float(r.get("close", 0.0))
                volar = float(r.get("volar_score", 0.0))
                cursor.execute("""
                    INSERT OR REPLACE INTO picks_history
                    (pick_date, symbol, rank, industry, regime, signal_type, status, entry_price, ret_1w, ret_1m, ret_since, last_px_date, volar_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (target_date, sym, rnk, ind, regime_str, sig_str, "ACTIVE", px, None, None, 0.0, target_date, volar))

            # Update returns for past active picks using current close prices from prices table
            px_map = dict(zip(top_df["symbol"], top_df["close"]))
            cursor.execute("SELECT pick_date, symbol, entry_price FROM picks_history WHERE status='ACTIVE' AND pick_date != ?", (target_date,))
            active_picks = cursor.fetchall()
            for pdate, sym, entry in active_picks:
                curr_px = None
                last_px_date = target_date
                if sym in px_map:
                    curr_px = float(px_map[sym])
                else:
                    cursor.execute(
                        "SELECT close, date FROM prices WHERE symbol=? AND date <= ? ORDER BY date DESC LIMIT 1",
                        (sym, target_date)
                    )
                    row = cursor.fetchone()
                    if row and row[0] is not None:
                        curr_px = float(row[0])
                        last_px_date = str(row[1])

                if curr_px is not None and entry > 0:
                    ret_s = round((curr_px / entry - 1.0) * 100.0, 2)
                    cursor.execute("""
                        UPDATE picks_history
                        SET ret_since=?, last_px_date=?
                        WHERE pick_date=? AND symbol=?
                    """, (ret_s, last_px_date, pdate, sym))

            conn.commit()
        except Exception as e:
            self.log(f"Warning: Failed to record picks history ({e})")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def run_scan(
        self,
        as_of_date: Optional[str] = None,
        universe_mode: Optional[str] = None,
        top_n: Optional[int] = None,
        lookback_days: Optional[int] = None,
        max_per_sector: Optional[int] = None,
        export_csv: bool = True,
        export_excel: bool = True,
        auto_update_universe: bool = True,
        allow_stale_data: bool = False,
        send_telegram: bool = False,
        auto_download_excel: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
        use_residual_momentum: bool = False,
        benchmark: Optional[str] = None,
        **kwargs,
    ) -> Tuple[pd.DataFrame, Dict, Dict, Dict, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Executes end-to-end screener pipeline on SQLite universe with institutional Phase 4 hardening.
        Returns: (top_df, breadth_results, sector_results, regime_info, top_etf_df, delivery_df)
        """
        t0 = time.time()
        from .settings import load_investing_settings
        st = load_investing_settings(self.base_dir)
        universe_mode = universe_mode or str(st.get("universe_mode", "NIFTY750"))
        top_n = int(top_n if top_n is not None else st.get("top_n", self.config.top_n_candidates))
        max_per_sector = int(max_per_sector if max_per_sector is not None else st.get("max_per_sector", self.config.max_per_sector))
        self.atr_stop_multiplier = float(st.get("atr_stop_multiplier", self.config.atr_stop_multiplier))
        effective_lookback_days = lookback_days or int(st.get("lookback_days", self.config.lookback_calendar_days))

        # Capture pre-scan database status for audit tracking
        pre_db_latest = None
        pre_row_count = 0
        try:
            with get_connection(read_only=True) as conn:
                r = conn.execute("SELECT COUNT(*), MAX(date) FROM prices;").fetchone()
                if r:
                    pre_row_count = int(r[0]) if r[0] is not None else 0
                    pre_db_latest = r[1]
        except Exception as e_pre:
            self.log(f"Database pre-check notice: {e_pre}")

        gdrive_backed_up = False
        dates_fetched = 0

        # 0. Dynamic Market Data Auto-Sync & Fail-Closed Date Resolution
        if as_of_date is not None:
            # Explicit date requested: Verify date is present and valid in SQLite
            ok, resolved_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date=as_of_date)
            if not ok:
                raise DataUnavailableError(diag.get("error", f"Requested date '{as_of_date}' has insufficient or no valid data in SQLite prices table."))
            target_date = resolved_date
            db_audit = {
                "is_updated": False,
                "pre_latest_date": pre_db_latest,
                "post_latest_date": pre_db_latest,
                "pre_row_count": pre_row_count,
                "post_row_count": pre_row_count,
                "new_rows_added": 0,
                "dates_fetched": 0,
                "gdrive_backed_up": False,
            }
        else:
            # Unspecified date: Determine expected latest EOD and sync if needed
            expected_session = get_expected_latest_eod()
            self.log(f"Unspecified date scan: latest expected completed market session is {expected_session}")

            if auto_update_universe:
                self.log("Auto-Sync Active: Checking NSE archives for latest market data...")
                old_mutation_flag = os.environ.get("MIP_ALLOW_PROD_MUTATION")
                try:
                    os.environ["MIP_ALLOW_PROD_MUTATION"] = "1"
                    from .auto_fetch import PydroidAutoFetch
                    fetcher = PydroidAutoFetch(self.base_dir)
                    sync_res = fetcher.sync_universe(dry_run=False)
                    dates_fetched = sync_res.get("dates_fetched", 0)
                    if dates_fetched > 0:
                        self.log(f"✓ Successfully fetched and saved {dates_fetched} new market session(s) to SQLite universe!")
                        try:
                            from scripts.cloud_sync import push_universe_to_gdrive
                            p_res = push_universe_to_gdrive(verbose=True)
                            p_ok = p_res[0] if isinstance(p_res, tuple) else bool(p_res)
                            gdrive_backed_up = bool(p_ok)
                        except Exception as e_push:
                            self.log(f"Drive backup notice: {e_push}")
                    else:
                        self.log(f"Auto-fetch status: {sync_res.get('status')} - {sync_res.get('message', '')}")
                except Exception as e:
                    self.log(f"Auto-update universe exception: {e}")
                finally:
                    if old_mutation_flag is not None:
                        os.environ["MIP_ALLOW_PROD_MUTATION"] = old_mutation_flag
                    else:
                        os.environ.pop("MIP_ALLOW_PROD_MUTATION", None)

            # Post-sync database state evaluation
            post_db_latest = pre_db_latest
            post_row_count = pre_row_count
            try:
                with get_connection(read_only=True) as conn:
                    r = conn.execute("SELECT COUNT(*), MAX(date) FROM prices;").fetchone()
                    if r:
                        post_row_count = int(r[0]) if r[0] is not None else 0
                        post_db_latest = r[1]
            except Exception as e_post:
                self.log(f"Database post-check notice: {e_post}")

            new_rows_added = max(0, post_row_count - pre_row_count)
            is_updated = (new_rows_added > 0) or (post_db_latest != pre_db_latest) or (dates_fetched > 0)

            db_audit = {
                "is_updated": is_updated,
                "pre_latest_date": pre_db_latest,
                "post_latest_date": post_db_latest,
                "pre_row_count": pre_row_count,
                "post_row_count": post_row_count,
                "new_rows_added": new_rows_added,
                "dates_fetched": dates_fetched,
                "gdrive_backed_up": gdrive_backed_up,
            }

            if is_updated:
                self.log(f"💾 DATABASE AUDIT: UPDATED! (+{new_rows_added:,} rows committed, latest date now {post_db_latest})")
                if gdrive_backed_up:
                    self.log("💾 Google Drive: Successfully backed up updated database to Google Drive.")
            else:
                self.log(f"💾 DATABASE AUDIT: VERIFIED UP-TO-DATE (Latest date {post_db_latest}, {post_row_count:,} rows)")

            # Verify SQLite contains the expected latest session (Fail-Closed)
            ok, resolved_date, diag = resolve_latest_valid_eod(base_dir=self.base_dir, as_of_date=None, allow_stale=allow_stale_data)
            if not ok:
                db_latest = diag.get("db_latest", "UNKNOWN")
                err_msg = (
                    f"CRITICAL: LATEST MARKET DATA UNAVAILABLE\n"
                    f"Expected completed market session: {expected_session}\n"
                    f"Database latest EOD date: {db_latest}\n"
                    f"Status: {diag.get('status')}\n"
                    f"Diagnostic: {diag.get('error')}\n"
                    f"A production scan with an unspecified date CANNOT execute on stale market data. FAIL CLOSED."
                )
                self.log(err_msg)
                raise StaleDataError(err_msg)
            target_date = resolved_date

        u_label = get_universe_label(universe_mode)
        self.log(f"Starting Production Momentum Scan as of {target_date} [{u_label}]...")

        target_dt = datetime.datetime.strptime(target_date, "%Y-%m-%d")
        start_str = (target_dt - datetime.timedelta(days=effective_lookback_days)).strftime("%Y-%m-%d")

        eff_benchmark = benchmark or getattr(self, "benchmark_name", "NIFTY500")

        # 1. Market Regime & Benchmark Evaluation (Fail-Closed with allow_stale_data resilience)
        if hasattr(self, "auto_fetch") and self.auto_fetch and eff_benchmark == "NIFTY500":
            try:
                bm_df_check = self.load_benchmark(benchmark_override=eff_benchmark)
                if bm_df_check.empty or str(bm_df_check["date"].max()) < target_date:
                    self.auto_fetch.sync_benchmark()
            except Exception as e_bmsync:
                self.log(f"Benchmark auto-sync notice: {e_bmsync}")

        regime_info = self.evaluate_regime(target_date, benchmark_override=eff_benchmark)
        market_bullish = bool(regime_info.get("is_normal_regime", False))
        bm_status = regime_info.get("status", "UNKNOWN")
        is_bm_healthy = bm_status not in ("INVALID", "STALE", "UNAVAILABLE", "CORRUPT")
        if not is_bm_healthy and allow_stale_data and bm_status in ("STALE", "PARTIAL"):
            self.log(f"WARNING: Benchmark data status is [{bm_status}], but allow_stale_data=True. Proceeding with forward-filled benchmark for RS evaluation.")
            is_bm_healthy = True

        # 2. Loading Bars from SQLite
        self.log(f"Loading bars from SQLite ({start_str} to {target_date})...")
        raw_bars = load_bars(start_date=start_str, end_date=target_date, include_delisted=True)

        active_today = set(raw_bars[raw_bars["date"] == target_date]["symbol"].unique())
        
        # Universe constituent filtering (Nifty 500 / Nifty 750 / All Active)
        u_constituents = load_universe_constituents(universe_mode)
        if u_constituents:
            initial_count = len(active_today)
            candidate_universe = active_today.intersection(u_constituents)
            self.log(f"Universe Filter [{u_label}]: {len(candidate_universe):,} / {initial_count:,} active symbols matched.")
        else:
            candidate_universe = active_today
            self.log(f"Universe Filter [{u_label}]: Evaluating all {len(candidate_universe):,} active symbols.")

        # 3. Security Bar Data Validation & Geometric Invariant Gating
        self.log("Validating security bars, OHLCV geometries, and observation histories...")
        valid_symbols = []
        cleaned_frames = []
        candidate_explanations: List[CandidateExplanation] = []
        reason_counter = Counter()

        # Group bars by symbol for individual validation
        grouped_bars = dict(tuple(raw_bars.groupby("symbol")))

        # Dynamic reload of corporate actions for point-in-time safety
        try:
            from .data_engine import load_applied_corporate_actions
            known_ca = load_applied_corporate_actions(end_date=target_date)
            self.anomaly_detector.set_corporate_actions(known_ca)
        except Exception:
            pass

        unresolved_anomalies_count = 0
        ca_status_map = {}

        for sym in sorted(candidate_universe):
            df_sym = grouped_bars.get(sym)
            sec_id = self.identity_mgr.resolve_security_id(sym, target_date)
            sector_val = self.sector_map.get(sym, "OTHER")

            # Phase 9: Corporate-Action-Aware Analytical Price Engine (Three-Tier Layer)
            # Transforms raw market series into analytical price series (Point-in-Time safe):
            # - Continuous backward factor adjustment for enterprise-preserving actions (BONUS/SPLIT)
            # - Boundary history partitioning for enterprise-altering reorganizations (DEMERGER)
            # - Fail-closed quarantine for unresolved structural drops > 40%
            if df_sym is not None and not df_sym.empty:
                df_sym, ca_diag = self.analytical_engine.derive_analytical_series(
                    sym, df_sym, as_of_date=target_date
                )
                if ca_diag.get("treatment") == "CONTINUOUS_BACKWARD_ADJUSTMENT":
                    ca_status_map[sym] = "ADJUSTED_FACTOR"
                elif ca_diag.get("treatment") == "BOUNDARY_HISTORY_PARTITIONING":
                    ca_status_map[sym] = "PARTITIONED_REORG"

                if ca_diag.get("is_blocked_unresolved"):
                    unresolved_anomalies_count += 1
                    ca_status_map[sym] = "BLOCKED_UNRESOLVED"
                    rcode = ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT.value
                    reason_counter[rcode] += 1
                    candidate_explanations.append(CandidateExplanation(
                        symbol=sym,
                        security_id=sec_id,
                        sector=sector_val,
                        close=float(df_sym["close"].iloc[-1]),
                        high_252=0.0,
                        ema200=0.0,
                        rs_ratio=0.0,
                        rs_ema200=0.0,
                        ret_252=0.0,
                        vol_252=0.0,
                        volar_score=0.0,
                        rank=None,
                        is_qualified=False,
                        reason_code=rcode,
                        diagnostic_details=f"Blocked: {ca_diag.get('unresolved_reason')}",
                    ))
                    continue

            val_res: ValidationResult = self.validator.validate_security_bars(
                symbol=sym,
                df=df_sym,
                as_of_date=target_date,
            )

            if not val_res.is_valid:
                reason_counter[val_res.reason_code.value] += 1
                candidate_explanations.append(CandidateExplanation(
                    symbol=sym,
                    security_id=sec_id,
                    sector=sector_val,
                    close=float(df_sym["close"].iloc[-1]) if (df_sym is not None and not df_sym.empty) else 0.0,
                    high_252=0.0,
                    ema200=0.0,
                    rs_ratio=0.0,
                    rs_ema200=0.0,
                    ret_252=0.0,
                    vol_252=0.0,
                    volar_score=0.0,
                    rank=None,
                    is_qualified=False,
                    reason_code=val_res.reason_code.value,
                    diagnostic_details=val_res.message,
                ))
            else:
                # Phase 4.1 Structural Discontinuity & Corporate Reorganization Gate
                is_clean, block_anomaly = self.anomaly_detector.is_security_clean(
                    symbol=sym,
                    df=val_res.cleaned_df,
                    as_of_date=target_date,
                )
                if not is_clean and block_anomaly is not None:
                    unresolved_anomalies_count += 1
                    ca_status_map[sym] = "REVIEW_REQUIRED"
                    rcode = block_anomaly.reason_code.value
                    reason_counter[rcode] += 1
                    candidate_explanations.append(CandidateExplanation(
                        symbol=sym,
                        security_id=sec_id,
                        sector=sector_val,
                        close=float(val_res.cleaned_df["close"].iloc[-1]),
                        high_252=0.0,
                        ema200=0.0,
                        rs_ratio=0.0,
                        rs_ema200=0.0,
                        ret_252=0.0,
                        vol_252=0.0,
                        volar_score=0.0,
                        rank=None,
                        is_qualified=False,
                        reason_code=rcode,
                        diagnostic_details=f"Blocked: {block_anomaly.anomaly_type} on {block_anomaly.date} (ratio: {block_anomaly.price_ratio}x) - {block_anomaly.explanation or 'Unresolved structural price event'}",
                    ))
                else:
                    ca_status_map[sym] = "CLEAN"
                    valid_symbols.append(sym)
                    cleaned_frames.append(val_res.cleaned_df)

        if cleaned_frames:
            bars = pd.concat(cleaned_frames, ignore_index=True)
            bars = bars.sort_values(by=["symbol", "date"]).reset_index(drop=True)
        else:
            bars = pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close", "volume"])

        # 4. Momentum Factors Calculation on Validated Bars
        self.log("Computing EMAs, rolling highs/lows, ATR-14, volatility, and returns...")
        
        # Factor windows strictly enforced from configuration
        bars["high_252"] = bars.groupby("symbol")["high"].transform(
            lambda s: s.rolling(self.config.rolling_high_bars).max()
        )
        bars["low_252"] = bars.groupby("symbol")["low"].transform(
            lambda s: s.rolling(self.config.rolling_low_bars).min()
        )
        bars["ema_200"] = bars.groupby("symbol")["close"].transform(
            lambda s: s.ewm(span=self.config.ema_trend_span, adjust=True, min_periods=self.config.min_history_ema).mean()
        )
        bars["ema_50"] = bars.groupby("symbol")["close"].transform(
            lambda s: s.ewm(span=self.config.ema_intermediate_span, adjust=True, min_periods=20).mean()
        )
        bars["ema_20"] = bars.groupby("symbol")["close"].transform(
            lambda s: s.ewm(span=self.config.ema_regime_span, adjust=True, min_periods=10).mean()
        )

        # 252-day Return: Close[t] / Close[t - 252] - 1.0 (calendar aligned lookback)
        bars["ret_252"] = bars.groupby("symbol")["close"].transform(
            lambda s: _calc_calendar_aligned_return(s, lookback=self.config.momentum_lookback_bars)
        )
        bars["ret_1y"] = bars["ret_252"] * 100.0
        bars["ret_21"] = bars.groupby("symbol")["close"].transform(
            lambda s: s / s.shift(21).fillna(s.iloc[0]) - 1.0
        )
        bars["ret_63"] = bars.groupby("symbol")["close"].transform(
            lambda s: s / s.shift(63).fillna(s.iloc[0]) - 1.0
        )
        bars["ret_1m"] = bars["ret_21"] * 100.0
        bars["ret_3m"] = bars["ret_63"] * 100.0
        bars["sector"] = bars["symbol"].map(lambda sym: self.sector_map.get(sym, "OTHER"))

        # Volatility & Volar Score
        bars["ret_1d"] = bars.groupby("symbol")["close"].pct_change().fillna(0.0)
        bars["vol_252"] = bars.groupby("symbol")["ret_1d"].transform(
            lambda s: s.rolling(self.config.volatility_lookback_bars, min_periods=min(251, len(s) - 1)).std(ddof=1) * np.sqrt(252)
        ).clip(lower=self.config.volatility_floor).fillna(self.config.volatility_floor)
        bars["volar_score"] = bars["ret_252"] / bars["vol_252"].clip(lower=self.config.volatility_floor)
        bars["raw_volar_score"] = bars["volar_score"].copy()
        bars["residual_mom_score"] = np.nan

        if use_residual_momentum:
            try:
                self.log("Computing 2D rolling residual momentum against benchmark...")
                from nextgen.residual_momentum import compute_rolling_residual_momentum, compute_composite_momentum_score

                # Deduplicate (date, symbol) to ensure safe matrix pivoting
                bars_dedup = bars.drop_duplicates(subset=["date", "symbol"])
                stock_rets = bars_dedup.pivot(index="date", columns="symbol", values="ret_1d").fillna(0.0)

                b_df = self.load_benchmark(benchmark_override=eff_benchmark)
                if not b_df.empty and "close" in b_df.columns:
                    b_df["date"] = b_df["date"].astype(str)
                    b_df = b_df.drop_duplicates(subset=["date"]).sort_values("date")
                    b_df["bm_ret"] = b_df["close"].pct_change(fill_method=None).fillna(0.0)
                    b_series = pd.Series(b_df.set_index("date")["bm_ret"]).reindex(stock_rets.index).fillna(0.0)

                    res_df = compute_rolling_residual_momentum(
                        stock_returns=stock_rets,
                        bench_returns=b_series,
                        lookback=min(self.config.momentum_lookback_bars, len(stock_rets)),
                        skip_recent=21,
                    )
                    if target_date in res_df.index:
                        latest_res = res_df.loc[target_date]
                    elif not res_df.empty:
                        latest_res = res_df.iloc[-1]
                    else:
                        latest_res = pd.Series(0.0, index=stock_rets.columns)

                    bars["residual_mom_score"] = bars["symbol"].map(latest_res).fillna(0.0)
                    bars["volar_score"] = compute_composite_momentum_score(
                        volar_scores=bars["raw_volar_score"].to_numpy(),
                        residual_scores=bars["residual_mom_score"].to_numpy(),
                        volar_weight=0.40,
                        residual_weight=0.60,
                    )
                    self.log("✓ Residual momentum applied: blended 40% canonical Volar + 60% idiosyncratic residual momentum.")
            except Exception as e_res:
                self.log(f"Residual momentum computation notice: {e_res} - falling back to canonical Volar.")

        # ATR-14 Calculation
        prev_close = bars.groupby("symbol")["close"].shift(1)
        tr1 = bars["high"] - bars["low"]
        tr2 = (bars["high"] - prev_close).abs()
        tr3 = (bars["low"] - prev_close).abs()
        bars["tr"] = np.maximum(tr1, np.maximum(tr2, tr3))
        bars["atr_14"] = bars.groupby("symbol")["tr"].transform(
            lambda s: s.rolling(self.config.atr_period, min_periods=min(5, len(s))).mean()
        ).fillna(bars["close"] * 0.03)

        # 30-day Turnover & RSI-14
        bars["turnover"] = bars["close"] * bars["volume"]
        bars["turnover_30d"] = bars.groupby("symbol")["turnover"].transform(
            lambda s: s.rolling(30, min_periods=min(10, len(s))).mean()
        ).fillna(0.0)
        bars["turnover_30d_cr"] = (bars["turnover_30d"] / 1e7).round(2)

        def _calc_rsi(s, period=14):
            d = s.diff()
            g = d.clip(lower=0)
            l = -d.clip(upper=0)
            ag = g.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            al = l.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
            rs = ag / al.replace(0, np.nan)
            return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        bars["rsi_14"] = bars.groupby("symbol")["close"].transform(_calc_rsi).round(2)
        bars["max_move_60"] = bars.groupby("symbol")["ret_1d"].transform(
            lambda s: s.abs().rolling(60, min_periods=min(10, len(s))).max()
        ).fillna(0.0)
        bars["pct_above_ema200"] = ((bars["close"] / bars["ema_200"] - 1.0) * 100.0).round(2)

        # Benchmark mapping & Fail-Closed RS Ratio (Strict Point-In-Time)
        b_df = self.load_benchmark(benchmark_override=eff_benchmark)
        if not b_df.empty:
            b_df = b_df[b_df["date"].astype(str) <= target_date]
            bm_latest = str(b_df["date"].max())
            if bm_latest < target_date and (allow_stale_data or getattr(self, "allow_stale_data", False)):
                last_row = b_df[b_df["date"] == bm_latest].iloc[0].to_dict()
                last_row["date"] = target_date
                b_df = pd.concat([b_df, pd.DataFrame([last_row])], ignore_index=True)
                is_bm_healthy = True
        bm_map = dict(zip(b_df["date"], b_df["close"])) if not b_df.empty else {}
        bars["benchmark_close"] = bars["date"].map(bm_map)
        
        # If benchmark is missing or corrupt, avoid silent 1.0 fallback
        if is_bm_healthy:
            bars["benchmark_close"] = bars.groupby("symbol")["benchmark_close"].ffill().bfill()
            bars["rs_ratio_raw"] = bars["close"] / bars["benchmark_close"]
            bars["rs_ema_200"] = bars.groupby("symbol")["rs_ratio_raw"].transform(
                lambda s: s.ewm(span=self.config.ema_rs_span, adjust=True, min_periods=self.config.min_history_ema).mean()
            )
        else:
            bars["rs_ratio_raw"] = np.nan
            bars["rs_ema_200"] = np.nan

        # RRG calculation
        bars = compute_rrg_metrics(bars)

        # Target date cross-section snapshot
        snap = bars[bars["date"] == target_date].copy()
        if snap.empty:
            raise ValueError(f"No bars available for target date {target_date}")

        # Add canonical security identity
        snap["security_id"] = snap["symbol"].map(lambda sym: self.identity_mgr.resolve_security_id(sym, target_date))
        snap["corporate_action_status"] = snap["symbol"].map(ca_status_map).fillna("CLEAN")

        # Diagnostic flags on snapshot
        snap["extension_flag"] = np.where(
            snap["pct_above_ema200"] > 40.0, "⚠ EXT >40%",
            np.where(snap["pct_above_ema200"] > 25.0, "EXT >25%", "")
        )
        snap["liquidity_flag"] = np.where(
            snap["turnover_30d"] < 1e7, "⚠ LOW LIQ (<₹1Cr)", ""
        )
        snap["sanity_flag"] = np.where(
            snap["max_move_60"] > 0.35, "⚠ SANITY (>±35% 60d)", ""
        )
        snap["industry"] = snap["sector"]
        snap["above_sma50"] = snap["close"] > snap["ema_50"]
        snap["above_sma100"] = snap["close"] > snap["close"].rolling(100, min_periods=20).mean().fillna(snap["close"])
        snap["above_sma200"] = snap["close"] > snap["ema_200"]
        snap["rs_positive"] = snap["rs_ratio_raw"] > 1.0
        snap["trend_aligned"] = snap["close"] > snap["ema_200"]
        snap["elite"] = (snap["close"] > snap["ema_200"]) & (snap["close"] >= 0.85 * snap["high_252"])
        snap["at_52w_high"] = snap["close"] >= 0.99 * snap["high_252"]

        # 5. Market Breadth Engine
        self.log("Evaluating Market Breadth...")
        breadth_results = self.breadth_engine.compute_breadth(as_of_date=target_date, snapshot_df=snap)

        # 6. Strategy Filters & Diagnostic Evaluation
        snap["pass_f1_retrace"] = snap["close"] >= (self.config.retrace_threshold * snap["high_252"])
        snap["pass_f2_trend"] = snap["close"] > snap["ema_200"]
        snap["pass_f3_rs"] = is_bm_healthy & (snap["rs_ratio_raw"] > snap["rs_ema_200"])
        snap["pass_mom"] = (snap["ret_252"] > 0) & (snap["volar_score"] > 0)
        snap["pass_all_filters"] = (
            snap["pass_f1_retrace"] & snap["pass_f2_trend"] & snap["pass_f3_rs"] & snap["pass_mom"]
        )

        # Assemble CandidateExplanations for all validated scrips in snapshot
        for _, row in snap.iterrows():
            sym = str(row["symbol"]).strip().upper()
            sec_id = str(row["security_id"])
            sec = str(row["sector"])
            c_val = float(row["close"])
            h_val = float(row["high_252"]) if pd.notna(row["high_252"]) else 0.0
            ema_val = float(row["ema_200"]) if pd.notna(row["ema_200"]) else 0.0
            rs_val = float(row["rs_ratio_raw"]) if pd.notna(row["rs_ratio_raw"]) else 0.0
            rs_ema_val = float(row["rs_ema_200"]) if pd.notna(row["rs_ema_200"]) else 0.0
            ret_val = float(row["ret_252"]) if pd.notna(row["ret_252"]) else 0.0
            vol_val = float(row["vol_252"]) if pd.notna(row["vol_252"]) else 0.0
            volar_val = float(row["volar_score"]) if pd.notna(row["volar_score"]) else 0.0
            
            f1 = bool(row["pass_f1_retrace"])
            f2 = bool(row["pass_f2_trend"])
            f3 = bool(row["pass_f3_rs"])
            mom = bool(row["pass_mom"])
            all_p = bool(row["pass_all_filters"])

            if all_p:
                rcode = ScannerReasonCode.PASS.value
                if use_residual_momentum and "residual_mom_score" in snap.columns and pd.notna(row.get("residual_mom_score")):
                    res_s = float(row.get("residual_mom_score", 0.0))
                    raw_v = float(row.get("raw_volar_score", volar_val))
                    diag = f"Qualified: Composite Volar {volar_val:.4f} (Residual: {res_s:.4f}, Raw: {raw_v:.4f}, Ret: {ret_val*100:.1f}%, Vol: {vol_val*100:.1f}%)"
                else:
                    diag = f"Qualified: Volar {volar_val:.4f} (Ret: {ret_val*100:.1f}%, Vol: {vol_val*100:.1f}%)"
            elif not f1:
                rcode = ScannerReasonCode.BELOW_52W_HIGH_THRESHOLD.value
                diag = f"Close {c_val:.2f} < 80% of 52w High ({h_val:.2f})"
            elif not f2:
                rcode = ScannerReasonCode.BELOW_EMA200.value
                diag = f"Close {c_val:.2f} <= 200 EMA ({ema_val:.2f})"
            elif not is_bm_healthy:
                rcode = ScannerReasonCode.STALE_BENCHMARK.value if bm_status == "STALE" else ScannerReasonCode.INVALID_BENCHMARK.value
                diag = f"Benchmark regime validation failed: {bm_status}"
            elif not f3:
                rcode = ScannerReasonCode.RS_BELOW_EMA.value
                diag = f"RS {rs_val:.4f} <= RS 200 EMA ({rs_ema_val:.4f})"
            elif not mom:
                rcode = ScannerReasonCode.NEGATIVE_MOMENTUM.value
                diag = f"1Y Return {ret_val*100:.2f}% or Volar is non-positive"
            else:
                rcode = ScannerReasonCode.INVALID_OHLC.value
                diag = "Filter validation failure"

            reason_counter[rcode] += 1
            res_score = float(row.get("residual_mom_score", np.nan)) if pd.notna(row.get("residual_mom_score")) else None
            deliv_action = str(row.get("deliv_action", "APPROVED"))
            candidate_explanations.append(CandidateExplanation(
                symbol=sym,
                security_id=sec_id,
                sector=sec,
                close=c_val,
                high_252=h_val,
                ema200=ema_val,
                rs_ratio=rs_val,
                rs_ema200=rs_ema_val,
                ret_252=ret_val,
                vol_252=vol_val,
                volar_score=volar_val,
                rank=None,
                is_qualified=all_p,
                reason_code=rcode,
                diagnostic_details=diag,
                residual_mom_score=res_score,
                delivery_action=deliv_action,
            ))

        # 7. Deterministic 3-Tier Candidate Ranking & Defense-in-Depth Ranking Firewall
        # Primary: Volar DESC | Secondary: Ret_252 DESC | Tertiary: security_id ASC
        clean_qualified_symbols = {
            c.symbol for c in candidate_explanations
            if c.is_qualified and c.reason_code == ScannerReasonCode.PASS.value and c.symbol in valid_symbols
        }

        # Invariant: Unresolved corporate reorganizations or data-corrupted securities can NEVER enter ranking
        ranking_mask = snap["pass_all_filters"] & snap["symbol"].isin(clean_qualified_symbols)
        if "corporate_action_status" in snap.columns:
            ranking_mask = ranking_mask & (
                snap["corporate_action_status"].isin(["RESOLVED", "CLEAN", ""]) | snap["corporate_action_status"].isna()
            )
        if "security_health" in snap.columns:
            ranking_mask = ranking_mask & (~snap["security_health"].isin(["BLOCKED", "UNSAFE", "DEGRADED"]))

        passed_df = snap[ranking_mask].copy()
        passed_df = passed_df.sort_values(
            by=["volar_score", "ret_252", "security_id"],
            ascending=[False, False, True]
        ).reset_index(drop=True)

        # 8. Sector Concentration Hard Cap (Max 2 stocks per industry/sector)
        sec_counts = {}
        top_rows = []
        for _, r in passed_df.iterrows():
            sec = str(r.get("sector", "OTHER")).strip().upper()
            if sec_counts.get(sec, 0) < max_per_sector:
                top_rows.append(r)
                sec_counts[sec] = sec_counts.get(sec, 0) + 1
            if len(top_rows) >= top_n:
                break

        top_df = pd.DataFrame(top_rows).reset_index(drop=True) if top_rows else passed_df.head(top_n).copy()
        top_df["rank"] = range(1, len(top_df) + 1)

        # Mark rank & sector cap bypass in candidate explanations
        top_syms = set(top_df["symbol"]) if not top_df.empty else set()
        rank_map = dict(zip(top_df["symbol"], top_df["rank"])) if not top_df.empty else {}
        for c in candidate_explanations:
            if c.symbol in rank_map:
                c.rank = rank_map[c.symbol]
            elif c.is_qualified and c.symbol not in top_syms:
                c.bypassed_sector_cap = True
                c.diagnostic_details += f" | Bypassed: Sector hard cap of {max_per_sector} exceeded"

        # Dynamic Stop Loss
        mult = getattr(self, "atr_stop_multiplier", self.config.atr_stop_multiplier)
        top_df["stop_loss"] = (top_df["close"] - mult * top_df["atr_14"]).clip(lower=0.01).round(2)

        # 9. Sector Rotation Engine
        self.log("Evaluating Sector Rotation...")
        top_symbols = top_df["symbol"].tolist()
        sector_results = self.sector_engine.compute_sector_rotation(
            as_of_date=target_date,
            snapshot_df=snap,
            top_20_symbols=top_symbols,
        )

        # 10. Delivery Volume & Accumulation/Distribution
        self.log("Fetching NSE Delivery Accumulation/Distribution metrics...")
        try:
            delivery_df = self.delivery_manager.get_delivery_data(target_dt.date())
        except Exception:
            delivery_df = pd.DataFrame()

        if delivery_df is not None and not delivery_df.empty:
            dmap = delivery_df.set_index("symbol").to_dict(orient="index")
            top_df["deliv_per"] = top_df["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_per", dmap.get(s, {}).get("delivery_pct", np.nan)))
            top_df["deliv_qty"] = top_df["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_qty", dmap.get(s, {}).get("delivery_qty", np.nan)))
            top_df["deliv_times"] = top_df["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_times", dmap.get(s, {}).get("delivery_multiple_5d", np.nan)))
            top_df["deliv_val_cr"] = top_df["symbol"].map(lambda s: dmap.get(s, {}).get("delivery_value_cr", dmap.get(s, {}).get("deliv_val_cr", np.nan)))
            top_df["delivery_action"] = top_df["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_action", dmap.get(s, {}).get("action", "⚪ NEUTRAL")))
            snap["deliv_per"] = snap["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_per", dmap.get(s, {}).get("delivery_pct", np.nan)))
            snap["deliv_qty"] = snap["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_qty", dmap.get(s, {}).get("delivery_qty", np.nan)))
            snap["deliv_times"] = snap["symbol"].map(lambda s: dmap.get(s, {}).get("deliv_times", dmap.get(s, {}).get("delivery_multiple_5d", np.nan)))
            snap["deliv_val_cr"] = snap["symbol"].map(lambda s: dmap.get(s, {}).get("delivery_value_cr", dmap.get(s, {}).get("deliv_val_cr", np.nan)))

        # Position Sizing (ATR Risk-Parity for ₹1L Portfolio)
        total_cap = self.config.nominal_portfolio_capital
        risk_budget = total_cap * self.config.risk_budget_pct
        qtys, vals = [], []
        for _, r in top_df.iterrows():
            p = float(r["close"])
            a = float(r["atr_14"])
            rps = max(2.0 * a, p * 0.02)
            q = int(risk_budget // rps) if (rps > 0 and p > 0) else 0
            q = max(0, min(q, int((total_cap * 0.25) // p))) if p > 0 else 0
            qtys.append(q if market_bullish else 0)
            vals.append(round(q * p, 2) if market_bullish else 0.0)
        top_df["target_qty"] = qtys
        top_df["target_val"] = vals

        # Map industry rank and rotation state
        ind_rank_map = {s["sector"]: s["rank"] for s in sector_results.get("sectors", [])}
        ind_rot_map = {s["sector"]: s.get("rotation_state", "NEUTRAL") for s in sector_results.get("sectors", [])}
        top_df["industry_rank"] = top_df["sector"].map(ind_rank_map).fillna(99).astype(int)
        top_df["rotation_state"] = top_df["sector"].map(ind_rot_map).fillna("NEUTRAL")

        def _assign_tier(row):
            q = str(row.get("rrg_quadrant", "UNKNOWN")).upper()
            rot = str(row.get("rotation_state", "NEUTRAL")).upper()
            if (q == "LEADING" and "UPTREND" in rot) or (q == "IMPROVING" and "RECOVERY" in rot):
                t = "TIER-1 (Leading + Uptrend)"
            elif q in ["LEADING", "IMPROVING"]:
                t = "TIER-2 (RRG right side)"
            else:
                t = "TIER-3 (All)"
            return f"HOLD (BEAR - {t})" if not market_bullish else t

        top_df["selection_tier"] = top_df.apply(_assign_tier, axis=1)
        top_df["tradingview"] = top_df["symbol"].map(lambda s: f"https://in.tradingview.com/chart/?symbol=NSE:{s}")

        # Record picks into persistent SQLite table
        self._record_picks_history(target_date, top_df, market_bullish)

        # 11. Definedge Momentify ALL-ONE ETF Momentum Engine
        self.log("Scanning Definedge Momentify ALL-ONE ETFs...")
        top_etf_df = None
        etf_ranking_df = None
        try:
            all_one = self.etf_engine.get_all_one_universe()
            if not all_one.empty:
                etf_ranking_df, top_etf_df = self.etf_engine.run_etf_scan(all_one, market_bullish=market_bullish, as_of_date=target_date)
                self.log(f"Ranked {len(etf_ranking_df)} ALL-ONE ETFs | Top {len(top_etf_df)} Picks Selected")
        except Exception as e:
            self.log(f"Warning: ETF scan encountered an issue: {e}")

        # 12. Health Governance & Multi-Barrier Actionable BUY Firewall
        health_report = self.health_monitor.evaluate_health(
            requested_count=len(candidate_universe),
            processed_count=len(valid_symbols),
            benchmark_status=bm_status,
            unresolved_anomalies_count=unresolved_anomalies_count,
        )
        if not market_bullish or health_report.state == ScannerHealthState.BLOCKED or not is_bm_healthy:
            health_report.allow_actionable_buys = False
            top_df["allow_buy"] = False
            top_df["signal_type"] = "BEAR_HOLD"
        else:
            top_df["allow_buy"] = True
            top_df["signal_type"] = "BUY"

            # Candidate-level fail-closed verification:
            # Trace every ticket through security_health, corporate_action_status, and data_quality_status
            clean_syms_set = set(clean_qualified_symbols)
            for idx, row in top_df.iterrows():
                sym = str(row["symbol"]).strip().upper()
                sec_health = str(row.get("security_health", "HEALTHY")).upper()
                ca_status = str(row.get("corporate_action_status", "CLEAN")).upper()

                is_safe = (
                    sym in clean_syms_set
                    and sec_health not in ("BLOCKED", "UNSAFE", "DEGRADED")
                    and ca_status not in ("REVIEW_REQUIRED", "UNRESOLVED", "BLOCKED", "UNSAFE")
                )
                if not is_safe:
                    top_df.at[idx, "allow_buy"] = False
                    top_df.at[idx, "signal_type"] = "BLOCKED_HOLD"
                    top_df.at[idx, "target_qty"] = 0
                    top_df.at[idx, "target_val"] = 0.0

        self.last_health_report = health_report

        # 13. Quality & Diagnostic Report Generation
        reports_dir = self.base_dir / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        scan_runtime = time.time() - t0

        report_data = self.quality_reporter.generate_report(
            as_of_date=target_date,
            universe_label=u_label,
            health_report=health_report,
            explanations=candidate_explanations,
            reason_counts=dict(reason_counter),
            benchmark_info=regime_info,
            runtime_seconds=scan_runtime,
            benchmark_name=eff_benchmark,
            alpha_overlays={
                "residual_momentum": bool(use_residual_momentum),
                "vol_targeting": bool(use_vol_targeting),
                "delivery_veto": bool(use_delivery_veto),
            },
        )
        self.last_scan_quality = report_data
        self.quality_reporter.export_json(report_data, reports_dir / "scan_quality.json")
        self.quality_reporter.export_markdown(report_data, reports_dir / "scan_quality.md")

        # 14. Export CSV & 14-Sheet Excel
        if export_csv:
            out_csv = reports_dir / "screener_output_live.csv"

            # Assemble full qualified candidates up to rank 100 for live portfolio exit buffer retention
            export_rows = []
            top_sym_set = set(top_df["symbol"]) if not top_df.empty else set()
            top_row_map = {r["symbol"]: r for _, r in top_df.iterrows()}

            # Candidates in passed_df have raw momentum rank 1 to len(passed_df)
            for rank_idx, (_, r) in enumerate(passed_df.head(100).iterrows()):
                sym = r["symbol"]
                row_dict = dict(r)
                row_dict["rank"] = rank_idx + 1
                row_dict["date"] = target_date
                row_dict["security_id"] = r.get("security_id", f"SEC_{sym}")

                if sym in top_sym_set:
                    top_r = top_row_map[sym]
                    row_dict["allow_buy"] = top_r.get("allow_buy", market_bullish)
                    row_dict["signal_type"] = top_r.get("signal_type", "BUY")
                    row_dict["target_qty"] = top_r.get("target_qty", 0)
                    row_dict["target_val"] = top_r.get("target_val", 0.0)
                    row_dict["stop_loss"] = top_r.get("stop_loss", round(max(0.01, float(r["close"]) - mult * float(r.get("atr_14", 0.0))), 2))
                    row_dict["selection_tier"] = top_r.get("selection_tier", "TIER-3 (All)")
                    row_dict["reason_code"] = top_r.get("reason_code", ScannerReasonCode.PASS.value)
                else:
                    row_dict["allow_buy"] = False
                    row_dict["signal_type"] = "BUFFER_HOLD"
                    row_dict["target_qty"] = 0
                    row_dict["target_val"] = 0.0
                    atr_val = float(r.get("atr_14", 0.0))
                    row_dict["stop_loss"] = round(max(0.01, float(r["close"]) - mult * atr_val), 2)
                    row_dict["selection_tier"] = "BUFFER (Hold-Only)"
                    if rank_idx + 1 <= top_n:
                        row_dict["reason_code"] = ScannerReasonCode.SECTOR_CAP_EXCEEDED.value
                    else:
                        row_dict["reason_code"] = ScannerReasonCode.PASS.value

                export_rows.append(row_dict)

            full_export_df = pd.DataFrame(export_rows) if export_rows else top_df.copy()

            export_cols = [
                "rank", "symbol", "security_id", "date", "close", "sector", "volar_score", "ret_1y", "vol_252",
                "high_252", "ema_200", "atr_14", "stop_loss", "rrg_quadrant", "rrg_rs_ratio",
                "rrg_rs_momentum", "pass_f1_retrace", "pass_f2_trend", "pass_f3_rs",
                "signal_type", "allow_buy", "corporate_action_status", "security_health", "reason_code",
                "target_qty", "target_val", "selection_tier"
            ]
            avail_cols = [c for c in export_cols if c in full_export_df.columns]
            full_export_df[avail_cols].to_csv(out_csv, index=False)
            self.log(f"Exported {len(full_export_df)} screener candidates (Top {len(top_df)} buys + buffer) to {out_csv}")

        chart_paths = {}
        try:
            from .visuals import generate_all_visuals
            self.log(f"Generating publication-quality charts & tearsheets [{u_label}]...")
            ind_hist_df = self.excel_generator._build_industry_history_df(target_date, bars)
            b_hist_df = self.excel_generator._build_breadth_history_df(target_date, bars, u_label)
            chart_paths = generate_all_visuals(
                as_of_date=target_date,
                breadth_data=breadth_results,
                sector_data=sector_results,
                top_df=top_df,
                ind_hist_df=ind_hist_df,
                breadth_hist_df=b_hist_df,
                universe_label=u_label,
                bars_df=bars,
            )
            top_df.attrs["chart_paths"] = chart_paths
        except Exception as e:
            self.log(f"Warning: Visuals generation skipped ({e})")

        excel_file = None
        if export_excel:
            try:
                self.log("Compiling institutional 14-sheet Excel workbook (with embedded charts & raw metrics)...")
                excel_file = self.excel_generator.generate_workbook(
                    as_of_date=target_date,
                    screener_df=snap[snap["pass_all_filters"]].sort_values("volar_score", ascending=False) if not snap[snap["pass_all_filters"]].empty else top_df,
                    top_candidates_df=top_df,
                    breadth_data=breadth_results,
                    sector_data=sector_results,
                    delivery_df=delivery_df,
                    etf_ranking_df=etf_ranking_df,
                    top_etf_df=top_etf_df,
                    market_bullish=market_bullish,
                    universe_label=u_label,
                    bars_df=bars,
                    chart_paths=chart_paths,
                    snap_df=snap,
                    benchmark=eff_benchmark,
                    use_residual_momentum=use_residual_momentum,
                    use_vol_targeting=use_vol_targeting,
                    use_delivery_veto=use_delivery_veto,
                    regime_info=regime_info,
                )
                self.log(f"Generated 14-sheet Excel workbook: {excel_file}")
                top_df.attrs["excel_path"] = excel_file
            except Exception as e:
                self.log(f"Warning: Excel workbook compilation failed: {e}")

        top_df.attrs["benchmark"] = eff_benchmark
        top_df.attrs["benchmark_name"] = eff_benchmark

        if auto_download_excel and excel_file and Path(excel_file).exists():
            try:
                from google.colab import files
                self.log(f"📥 Triggering browser download for {Path(excel_file).name}...")
                files.download(str(excel_file))
                self.log("✓ Automatic Excel download initiated.")
            except Exception as e_dl:
                self.log(f"Auto-download notice: {e_dl}")

        if send_telegram:
            try:
                from .telegram_sender import PydroidTelegramSender, format_telegram_alert
                tg_sender = PydroidTelegramSender()
                if tg_sender.is_configured():
                    alert_text = format_telegram_alert(
                        top_df=top_df,
                        breadth=breadth_results,
                        sectors=sector_results,
                        regime=regime_info,
                        as_of_date=target_date,
                        top_etf_df=top_etf_df,
                        delivery_df=delivery_df,
                        universe_label=u_label,
                        db_audit=db_audit,
                    )
                    tg_sender.send_message(alert_text)
                    chart_paths = top_df.attrs.get("chart_paths", {})
                    if chart_paths and "market_overview" in chart_paths:
                        tg_sender.send_photo(chart_paths["market_overview"], caption=f"📊 Market Overview & Breadth [{target_date}]")
                    excel_path = top_df.attrs.get("excel_path") or excel_file
                    if excel_path and Path(excel_path).exists():
                        tg_sender.send_document(Path(excel_path), caption=f"📑 Institutional Excel Workbook [{u_label}] ({target_date})")
                    self.log("✓ Dispatched institutional scan summary to Telegram.")
                else:
                    self.log("⚠ Telegram dispatch skipped: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID not configured.")
            except Exception as e_tg:
                self.log(f"Warning: Telegram dispatch error ({e_tg})")

        top_df.attrs["scanned_date"] = target_date
        top_df.attrs["target_date"] = target_date
        top_df.attrs["universe_label"] = u_label
        top_df.attrs["universe_mode"] = universe_mode
        top_df.attrs["health_report"] = health_report
        top_df.attrs["scan_quality"] = report_data
        top_df.attrs["db_audit"] = db_audit
        top_df.attrs["residual_momentum_enabled"] = bool(use_residual_momentum)
        return top_df, breadth_results, sector_results, regime_info, top_etf_df, delivery_df


def format_screener_tearsheet(
    top_df: pd.DataFrame,
    breadth: Dict,
    sectors: Dict,
    regime: Dict,
    as_of_date: str,
    top_etf_df: Optional[pd.DataFrame] = None,
    delivery_df: Optional[pd.DataFrame] = None,
    universe_label: Optional[str] = None,
    db_audit: Optional[Dict] = None,
    benchmark: Optional[str] = None,
) -> str:
    """Formats institutional ANSI terminal summary tearsheet with modern box typography and full lineage."""
    u_str = universe_label or top_df.attrs.get("universe_label", "NIFTY 750")
    eff_bm = benchmark or top_df.attrs.get("benchmark") or regime.get("benchmark_name", "NIFTY500")

    lines = []
    lines.append("┌────────────────────────────────────────────────────────────────────────┐")
    lines.append("│         PROJECT MIP — QUANTITATIVE MOMENTUM SCANNER TEARSHEET          │")
    lines.append(f"│                  Institutional Publication Edition  •  {as_of_date:<15}│")
    lines.append("└────────────────────────────────────────────────────────────────────────┘")

    # 0. Database Synchronization Audit
    db_audit_info = db_audit or top_df.attrs.get("db_audit")
    if db_audit_info:
        lines.append(f"\n[0] DATABASE SYNCHRONIZATION AUDIT")
        if db_audit_info.get("is_updated"):
            lines.append(f"  Audit Status:        UPDATED (Fresh market bars acquired)")
            lines.append(f"  Rows Added:          +{db_audit_info.get('new_rows_added', 0):,} rows committed to SQLite")
            lines.append(f"  Date Transition:     {db_audit_info.get('pre_latest_date')} ➔ {db_audit_info.get('post_latest_date')}")
            lines.append(f"  Total Rows:          {db_audit_info.get('post_row_count', 0):,} rows in prices table")
            if db_audit_info.get("gdrive_backed_up"):
                lines.append(f"  Google Drive Sync:   ✓ Backup completed to /MyDrive/MIP/universe.db")
        else:
            lines.append(f"  Audit Status:        VERIFIED UP-TO-DATE (No newer session required)")
            lines.append(f"  Latest Session:      {db_audit_info.get('post_latest_date')}")
            lines.append(f"  Total Rows:          {db_audit_info.get('post_row_count', 0):,} rows in prices table")

    # 1. Market Regime & Breadth
    lines.append(f"\n[1] MARKET REGIME & REFERENCE BENCHMARK")
    lines.append(f"  Target Universe:     {u_str}")
    lines.append(f"  Reference Benchmark: {eff_bm}")
    lines.append(f"  Benchmark Regime:    {regime.get('label', 'N/A')}")
    if regime.get("bm_close") and regime.get("bm_ema20"):
        c = float(regime["bm_close"])
        e = float(regime["bm_ema20"])
        pct = ((c / max(0.01, e)) - 1.0) * 100
        lines.append(f"  Benchmark vs 20 EMA: ₹{c:,.2f} vs ₹{e:,.2f} ({pct:+.2f}%)")

    b_tp = breadth.get("trend_participation", {})
    b_hp = breadth.get("high_proximity", {})
    b_nhl = breadth.get("net_highs_lows", {})
    b_reg = breadth.get("regime", {})
    lines.append(f"  Breadth State:       {b_reg.get('label', 'N/A')}")
    lines.append(f"  Trend Breadth:       >200 EMA: {b_tp.get('pct_above_200_ema', 0.0):.1f}% | >50 EMA: {b_tp.get('pct_above_50_ema', 0.0):.1f}% | >20 EMA: {b_tp.get('pct_above_20_ema', 0.0):.1f}%")
    lines.append(f"  High Proximity:      Within 20% of 52wH: {b_hp.get('pct_within_20pct_52wh', 0.0):.1f}% | Within 5%: {b_hp.get('pct_within_5pct_52wh', 0.0):.1f}%")
    lines.append(f"  52-Week Net Highs:   +{b_nhl.get('new_52w_highs', 0)} / -{b_nhl.get('new_52w_lows', 0)} (Net: {b_nhl.get('net_highs_lows', 0):+d})")

    # 2. Sector Rotation Summary
    lines.append(f"\n[2] SECTOR ROTATION RANKINGS")
    lines.append(f"  {'Rank':<5}{'Sector':<14}{'1M Ret':<10}{'Alpha 1M':<11}{'>200EMA':<10}{'RRG Quad':<12}{'Top20'}")
    lines.append("  " + "─" * 70)
    for s in sectors.get("sectors", [])[:6]:
        lines.append(
            f"  {s['rank']:<5}{s['sector']:<14}{s['ret_1m']:+6.2f}%   {s['alpha_1m']:+6.2f}%    "
            f"{s['breadth_200_pct']:5.1f}%    {s['rrg_quadrant']:<12}{s['top_20_count']}"
        )

    # 3. Top Candidates (Sector Hard Cap & ATR Stop Loss)
    res_mom_active = bool(top_df.attrs.get("residual_momentum_enabled")) if hasattr(top_df, "attrs") else False
    if res_mom_active:
        lines.append(f"\n[3] TOP MOMENTUM CANDIDATES (RESIDUAL MOMENTUM ACTIVE: 40% VOLAR + 60% IDIOSYNCRATIC ALPHA)")
        lines.append(f"  {'Rank':<5}{'Symbol':<12}{'Close (₹)':<11}{'Stop Loss':<11}{'Sector':<12}{'Volar':<7}{'Res Alpha':<11}{'1Y Ret':<9}{'RRG Quad'}")
        lines.append("  " + "─" * 84)
        for _, row in top_df.iterrows():
            val = float(row.get('ret_1y', 0.0))
            ret_1y_pct = val if abs(val) > 5.0 or val == 0.0 else val * 100.0
            sl_val = row.get('stop_loss', row['close'] * 0.94)
            res_val = f"{float(row['residual_mom_score']):+.3f}" if pd.notna(row.get('residual_mom_score')) else "-"
            lines.append(
                f"  {int(row['rank']):<5}{row['symbol']:<12}{row['close']:<11.2f}{sl_val:<11.2f}{row['sector']:<12}"
                f"{row['volar_score']:<7.2f}{res_val:<11}{ret_1y_pct:+6.1f}%   {row['rrg_quadrant']}"
            )
    else:
        lines.append(f"\n[3] TOP 20 MOMENTUM CANDIDATES (SECTOR HARD CAP: MAX 2/SECTOR)")
        lines.append(f"  {'Rank':<5}{'Symbol':<13}{'Close (₹)':<11}{'Stop Loss':<11}{'Sector':<12}{'Volar':<7}{'1Y Ret':<9}{'RRG Quad'}")
        lines.append("  " + "─" * 76)
        for _, row in top_df.iterrows():
            val = float(row.get('ret_1y', 0.0))
            ret_1y_pct = val if abs(val) > 5.0 or val == 0.0 else val * 100.0
            sl_val = row.get('stop_loss', row['close'] * 0.94)
            lines.append(
                f"  {int(row['rank']):<5}{row['symbol']:<13}{row['close']:<11.2f}{sl_val:<11.2f}{row['sector']:<12}"
                f"{row['volar_score']:<7.2f}{ret_1y_pct:+6.1f}%   {row['rrg_quadrant']}"
            )

    # 4. Top 7 ALL-ONE Momentify ETFs
    if top_etf_df is not None and not top_etf_df.empty:
        lines.append(f"\n[4] DEFINEDGE MOMENTIFY ALL-ONE ETF PICKS (TOP 7)")
        lines.append(f"  {'Rank':<5}{'Symbol':<13}{'Price (₹)':<11}{'Volar':<8}{'Target Qty':<12}{'Underlying Asset'}")
        lines.append("  " + "─" * 70)
        for idx, (_, r) in enumerate(top_etf_df.head(7).iterrows(), 1):
            lines.append(
                f"  {idx:<5}{r['symbol']:<13}{r['price']:<11.2f}{r['volar_score']:<8.2f}{int(r['target_qty']):<12}{r['underlying']}"
            )

    # 5. Institutional Delivery Accumulation Spikes
    if delivery_df is not None and not delivery_df.empty:
        spikes = delivery_df[delivery_df["delivery_value_cr"].fillna(0) >= 5.0].sort_values("deliv_per", ascending=False).head(4)
        if not spikes.empty:
            lines.append(f"\n[5] TOP INSTITUTIONAL DELIVERY SPIKES (₹5Cr+)")
            lines.append(f"  {'Symbol':<14}{'Deliv %':<10}{'Deliv Times':<13}{'Deliv Value':<14}{'Action'}")
            lines.append("  " + "─" * 64)
            for _, r in spikes.iterrows():
                dt_str = f"{r['deliv_times']:.1f}x" if pd.notna(r.get('deliv_times')) else "-"
                lines.append(
                    f"  {r['symbol']:<14}{r['deliv_per']:>6.1f}%    {dt_str:<13}₹{r['delivery_value_cr']:>6.1f} Cr     {r['deliv_action']}"
                )

    lines.append("════════════════════════════════════════════════════════════════════════")
    return "\n".join(lines)


# Institutional Alias
MomentumScanner = PydroidScanner
