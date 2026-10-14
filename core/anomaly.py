"""
pydroid_core/anomaly.py
Quantitative Market Data Anomaly Detection, Structural Discontinuity & Corporate Reorganization Gate.
Phase 4.1 Institutional Hardening for Project MIP Pydroid3.
Guarantees: An unexplained material structural price discontinuity never silently becomes a momentum signal.
"""

from dataclasses import dataclass
from enum import Enum
import re
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import numpy as np
import pandas as pd

from .config import MIPScannerConfig
from .reason_codes import ScannerReasonCode


class CorporateActionType(str, Enum):
    """Institutional taxonomy of corporate actions and structural reorganizations."""
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    DIVIDEND = "DIVIDEND"
    DEMERGER = "DEMERGER"
    SPIN_OFF = "SPIN_OFF"
    MERGER = "MERGER"
    AMALGAMATION = "AMALGAMATION"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    SCHEME_OF_ARRANGEMENT = "SCHEME_OF_ARRANGEMENT"
    RIGHTS = "RIGHTS"
    ENTITLEMENT = "ENTITLEMENT"
    RELISTING = "RELISTING"
    RESTRUCTURING = "RESTRUCTURING"
    UNKNOWN_MATERIAL_EVENT = "UNKNOWN_MATERIAL_EVENT"


def classify_corporate_action(subject: str) -> CorporateActionType:
    """
    Categorizes raw corporate action text or subject line into institutional taxonomy.
    Deterministic, regex-based, strictly non-speculative.
    """
    if not subject or not isinstance(subject, str):
        return CorporateActionType.UNKNOWN_MATERIAL_EVENT

    sub = subject.strip().lower()

    if re.search(r'(?:split|sub-division)', sub):
        return CorporateActionType.SPLIT
    elif re.search(r'bonus', sub):
        return CorporateActionType.BONUS
    elif re.search(r'dividend', sub):
        return CorporateActionType.DIVIDEND
    elif re.search(r'demerger|de-merger|demerge', sub):
        return CorporateActionType.DEMERGER
    elif re.search(r'spin[-_ ]*off', sub):
        return CorporateActionType.SPIN_OFF
    elif re.search(r'amalgamation|amalgamate', sub):
        return CorporateActionType.AMALGAMATION
    elif re.search(r'merger|merge', sub):
        return CorporateActionType.MERGER
    elif re.search(r'capital[-_ ]*reduction|reduction\s+of\s+capital|capital\s+reorgani[zs]ation', sub):
        return CorporateActionType.CAPITAL_REDUCTION
    elif re.search(r'scheme\s+(?:of\s+arrangement|related)|scheme', sub):
        return CorporateActionType.SCHEME_OF_ARRANGEMENT
    elif re.search(r'rights\s+(?:issue|entitlement)|entitlement', sub):
        return CorporateActionType.RIGHTS
    elif re.search(r'relisting|re-listing', sub):
        return CorporateActionType.RELISTING
    elif re.search(r'restructuring|re-structuring', sub):
        return CorporateActionType.RESTRUCTURING
    elif re.search(r'reconstruction|consolidation|reverse[-_ ]*split', sub):
        return CorporateActionType.SCHEME_OF_ARRANGEMENT
    else:
        return CorporateActionType.UNKNOWN_MATERIAL_EVENT


@dataclass
class AnomalyEvent:
    """Diagnostic details of a detected market data anomaly or corporate event."""
    symbol: str
    date: str
    anomaly_type: str
    price_ratio: float
    volume_multiple: float
    is_explained: bool
    explanation: Optional[str] = None
    severity: str = "WARN"   # WARN (informational/explained) or FAIL (blocks candidate)
    reason_code: ScannerReasonCode = ScannerReasonCode.PASS
    event_type: Optional[str] = None


class ScannerAnomalyDetector:
    """
    Institutional Anomaly Detection & Corporate Action Integrity Gate.
    Enforces the Core Security Principle:
    «An unexplained material structural price discontinuity must never silently become a valid momentum signal.»
    """

    def __init__(
        self,
        config: Optional[MIPScannerConfig] = None,
        known_corporate_actions: Optional[List[Dict[str, Any]]] = None,
    ):
        self.config = config or MIPScannerConfig()
        self.corporate_actions = known_corporate_actions or []
        self._action_lookup, self._actions_by_symbol = self._build_action_index()

    def _build_action_index(self) -> Tuple[Dict[Tuple[str, str], Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
        """Indexes corporate actions by (symbol, ex_date) and by symbol."""
        exact_lookup = {}
        by_symbol = defaultdict(list)
        for ca in self.corporate_actions:
            sym = str(ca.get("symbol", "")).strip().upper()
            ex = str(ca.get("ex_date", "")).strip()[:10]
            if sym and ex:
                # Normalize action type
                raw_type = ca.get("type", ca.get("action_type", ""))
                if isinstance(raw_type, CorporateActionType):
                    norm_type = raw_type.value
                elif isinstance(raw_type, str) and raw_type.upper() in CorporateActionType.__members__:
                    norm_type = raw_type.upper()
                else:
                    norm_type = classify_corporate_action(str(ca.get("subject", raw_type))).value
                
                enriched = dict(ca)
                enriched["symbol"] = sym
                enriched["ex_date"] = ex
                enriched["action_type"] = norm_type
                
                exact_lookup[(sym, ex)] = enriched
                by_symbol[sym].append(enriched)

        return exact_lookup, dict(by_symbol)

    def set_corporate_actions(self, actions: List[Dict[str, Any]]) -> None:
        """Dynamically reloads corporate actions ledger."""
        self.corporate_actions = actions
        self._action_lookup, self._actions_by_symbol = self._build_action_index()

    def get_reorganization_cutoff_date(self, symbol: str, as_of_date: str) -> Optional[str]:
        """
        Returns the latest ex_date of any structural corporate reorganization on or before as_of_date.
        For securities with corporate reorganizations (demergers, spin-offs, capital reductions, etc.),
        the post-reorganization price series starts at ex_date. Pre-reorganization unadjusted bars
        must be partitioned to guarantee zero recursive contamination in IIR filters (EMA200, RS_EMA200).
        """
        sym_clean = str(symbol).strip().upper()
        as_of_clean = str(as_of_date).strip()[:10]
        sym_actions = self._actions_by_symbol.get(sym_clean, [])

        reorg_types = {
            CorporateActionType.DEMERGER.value,
            CorporateActionType.SPIN_OFF.value,
            CorporateActionType.MERGER.value,
            CorporateActionType.AMALGAMATION.value,
            CorporateActionType.CAPITAL_REDUCTION.value,
            CorporateActionType.SCHEME_OF_ARRANGEMENT.value,
            CorporateActionType.RESTRUCTURING.value,
            CorporateActionType.UNKNOWN_MATERIAL_EVENT.value,
        }

        latest_ex: Optional[str] = None
        for ca in sym_actions:
            ex_d = str(ca.get("ex_date", ""))[:10]
            if not ex_d or ex_d > as_of_clean:
                # Anti-lookahead: Future corporate actions strictly ignored
                continue
            act_type = ca.get("action_type", "")
            if act_type in reorg_types:
                if latest_ex is None or ex_d > latest_ex:
                    latest_ex = ex_d
        return latest_ex

    def detect_anomalies(
        self,
        symbol: str,
        df: pd.DataFrame,
        as_of_date: str,
    ) -> List[AnomalyEvent]:
        """
        Scans security bars for extreme price dislocations, flash crashes, and corporate reorganizations.
        Point-In-Time (PIT) Enforced:
        - Never uses corporate actions with ex_date > as_of_date.
        - Never uses bars with date > as_of_date.
        """
        anomalies: List[AnomalyEvent] = []
        sym_clean = str(symbol).strip().upper()
        as_of_clean = str(as_of_date).strip()[:10]

        if df is None or len(df) < 2:
            return anomalies

        df_sorted = df.copy()
        df_sorted["date_clean"] = df_sorted["date"].astype(str).str.strip().str[:10]
        # PIT Temporal Filter
        df_sorted = df_sorted[df_sorted["date_clean"] <= as_of_clean].sort_values("date_clean").reset_index(drop=True)
        if len(df_sorted) < 2:
            return anomalies

        closes = df_sorted["close"].to_numpy(dtype=float)
        opens = df_sorted["open"].to_numpy(dtype=float) if "open" in df_sorted.columns else closes
        dates = df_sorted["date_clean"].to_numpy(dtype=str)
        volumes = df_sorted["volume"].to_numpy(dtype=float) if "volume" in df_sorted.columns else np.ones(len(closes))

        # --- GATE 1: Known Corporate Actions in Active Event Window (Point-in-Time) ---
        sym_actions = self._actions_by_symbol.get(sym_clean, [])
        for ca in sym_actions:
            ex_d = ca.get("ex_date", "")
            if not ex_d or ex_d > as_of_clean:
                # PIT Safety: Future corporate actions strictly ignored
                continue

            act_type = ca.get("action_type", "")
            factor = ca.get("factor")
            is_resolved = bool(ca.get("is_resolved", False))

            # Calculate trading sessions elapsed since the event
            sessions_since_event = int((dates >= ex_d).sum())
            if sessions_since_event == 0:
                # Event occurred before the first available price bar in df
                continue

            if sessions_since_event < self.config.min_reorganization_clean_sessions:
                # Event is inside the trailing 252-day lookback window: price history is potentially contaminated
                if act_type in (CorporateActionType.SPLIT.value, CorporateActionType.BONUS.value):
                    if factor is not None and float(factor) > 0:
                        # Authoritative mathematical split/bonus with confirmed factor
                        anomalies.append(AnomalyEvent(
                            symbol=sym_clean,
                            date=ex_d,
                            anomaly_type="CORPORATE_ACTION_SPLIT_BONUS",
                            price_ratio=float(factor),
                            volume_multiple=1.0,
                            is_explained=True,
                            explanation=f"Authorized {act_type} on {ex_d} with verified factor {factor}",
                            severity="WARN",
                            reason_code=ScannerReasonCode.PASS,
                            event_type=act_type,
                        ))
                    else:
                        # Split/bonus recorded without valid factor
                        anomalies.append(AnomalyEvent(
                            symbol=sym_clean,
                            date=ex_d,
                            anomaly_type="CORPORATE_ACTION_INVALID",
                            price_ratio=0.0,
                            volume_multiple=1.0,
                            is_explained=False,
                            explanation=f"{act_type} on {ex_d} lacks valid numerical adjustment factor",
                            severity="FAIL",
                            reason_code=ScannerReasonCode.CORPORATE_ACTION_INVALID,
                            event_type=act_type,
                        ))
                elif act_type == CorporateActionType.DIVIDEND.value:
                    # Cash dividend does not mutate prices under price-return methodology
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=ex_d,
                        anomaly_type="CORPORATE_ACTION_DIVIDEND",
                        price_ratio=1.0,
                        volume_multiple=1.0,
                        is_explained=True,
                        explanation=f"Cash dividend on {ex_d} (no price adjustment required)",
                        severity="WARN",
                        reason_code=ScannerReasonCode.PASS,
                        event_type=act_type,
                    ))
                elif act_type == CorporateActionType.UNKNOWN_MATERIAL_EVENT.value:
                    # Unknown material event: fail closed unconditionally
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=ex_d,
                        anomaly_type="UNKNOWN_MATERIAL_EVENT",
                        price_ratio=float(factor) if factor else 0.0,
                        volume_multiple=1.0,
                        is_explained=False,
                        explanation=f"Unknown material corporate event on {ex_d}: requires validation",
                        severity="FAIL",
                        reason_code=ScannerReasonCode.UNKNOWN_MATERIAL_EVENT,
                        event_type=act_type,
                    ))
                else:
                    # High-impact corporate reorganization: DEMERGER, SPIN_OFF, CAPITAL_REDUCTION, etc.
                    if is_resolved and factor is not None and float(factor) > 0:
                        anomalies.append(AnomalyEvent(
                            symbol=sym_clean,
                            date=ex_d,
                            anomaly_type="CORPORATE_ACTION_RESOLVED",
                            price_ratio=float(factor),
                            volume_multiple=1.0,
                            is_explained=True,
                            explanation=f"Resolved {act_type} on {ex_d} with verified factor {factor}",
                            severity="WARN",
                            reason_code=ScannerReasonCode.PASS,
                            event_type=act_type,
                        ))
                    else:
                        # Fail-closed institutional invariant: Unresolved structural reorganization cannot qualify
                        anomalies.append(AnomalyEvent(
                            symbol=sym_clean,
                            date=ex_d,
                            anomaly_type="CORPORATE_ACTION_REVIEW_REQUIRED",
                            price_ratio=float(factor) if factor else 0.0,
                            volume_multiple=1.0,
                            is_explained=False,
                            explanation=f"Unresolved {act_type} on {ex_d} within active momentum window ({sessions_since_event} sessions < {self.config.min_reorganization_clean_sessions} required)",
                            severity="FAIL",
                            reason_code=ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED,
                            event_type=act_type,
                        ))
            else:
                # 252+ clean sessions have elapsed since the reorganization; trailing window is fully post-event
                if is_resolved and factor is not None and float(factor) > 0:
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=ex_d,
                        anomaly_type="CORPORATE_ACTION_HISTORICAL",
                        price_ratio=float(factor),
                        volume_multiple=1.0,
                        is_explained=True,
                        explanation=f"Historical resolved {act_type} on {ex_d} aged out of momentum window ({sessions_since_event} >= 252 clean sessions)",
                        severity="WARN",
                        reason_code=ScannerReasonCode.PASS,
                        event_type=act_type,
                    ))
                elif act_type in (CorporateActionType.SPLIT.value, CorporateActionType.BONUS.value, CorporateActionType.DIVIDEND.value):
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=ex_d,
                        anomaly_type="CORPORATE_ACTION_HISTORICAL",
                        price_ratio=float(factor) if factor else 1.0,
                        volume_multiple=1.0,
                        is_explained=True,
                        explanation=f"Historical {act_type} on {ex_d} aged out ({sessions_since_event} >= 252 clean sessions)",
                        severity="WARN",
                        reason_code=ScannerReasonCode.PASS,
                        event_type=act_type,
                    ))
                else:
                    # Unresolved corporate reorganization older than 252 sessions:
                    # Fail-closed invariant: Unresolved reorganization cannot qualify or become actionable BUY
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=ex_d,
                        anomaly_type="CORPORATE_ACTION_REVIEW_REQUIRED",
                        price_ratio=float(factor) if factor else 0.0,
                        volume_multiple=1.0,
                        is_explained=False,
                        explanation=f"Unresolved historical {act_type} on {ex_d} ({sessions_since_event} sessions elapsed) requires corporate action review",
                        severity="FAIL",
                        reason_code=ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED,
                        event_type=act_type,
                    ))

        # --- GATE 2: Bar-by-Bar Discontinuity & Structural Price Integrity ---
        # Rolling historical daily returns for statistical baseline
        daily_returns = np.diff(closes) / closes[:-1]
        
        for i in range(1, len(closes)):
            prev_c = closes[i - 1]
            curr_c = closes[i]
            curr_o = opens[i]
            d = str(dates[i])[:10]

            if prev_c <= 0 or curr_c <= 0:
                continue

            ratio = curr_c / prev_c
            ret_abs = abs(curr_c / prev_c - 1.0)
            open_gap = abs(curr_o / prev_c - 1.0)
            
            # Trailing volatility estimate (min 15 sessions)
            hist_ret = daily_returns[max(0, i - 30):i]
            hist_std = float(np.std(hist_ret, ddof=1)) if len(hist_ret) >= 15 else 0.03
            hist_std = max(hist_std, 0.01)

            ca = self._action_lookup.get((sym_clean, d))
            ca_type = ca.get("action_type") if ca else None

            # Discontinuity Check 1: Structural Price Collapse / Drop (ratio <= 0.60, >= 40% drop)
            if ratio <= self.config.structural_price_drop_threshold:
                is_exp = False
                exp_text = None
                rcode = ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT

                if ca_type in (CorporateActionType.SPLIT.value, CorporateActionType.BONUS.value):
                    is_exp = True
                    exp_text = f"Explained by verified {ca_type}: ratio {ratio:.2f}"
                    rcode = ScannerReasonCode.PASS
                elif ca:
                    exp_text = f"Severe price drop of {(1.0 - ratio)*100:.1f}% on {d} linked to unverified {ca_type}"
                    rcode = ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED
                else:
                    exp_text = f"Severe unexplained price collapse of {(1.0 - ratio)*100:.1f}% on {d} (violates exchange circuit bounds)"
                    rcode = ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT

                anomalies.append(AnomalyEvent(
                    symbol=sym_clean,
                    date=d,
                    anomaly_type="STRUCTURAL_PRICE_DROP",
                    price_ratio=round(ratio, 4),
                    volume_multiple=1.0,
                    is_explained=is_exp,
                    explanation=exp_text,
                    severity="WARN" if is_exp else "FAIL",
                    reason_code=rcode,
                    event_type=ca_type,
                ))

            # Discontinuity Check 2: Structural Price Jump (ratio >= 1.60, >= 60% jump)
            elif ratio >= self.config.structural_price_jump_threshold:
                is_exp = False
                exp_text = None
                rcode = ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT

                if ca_type in (CorporateActionType.SCHEME_OF_ARRANGEMENT.value, "CONSOLIDATION", "REVERSE_SPLIT") and ca.get("is_resolved"):
                    is_exp = True
                    exp_text = f"Explained by verified reverse-split/consolidation: {ca.get('factor')}"
                    rcode = ScannerReasonCode.PASS
                elif ca:
                    exp_text = f"Extreme price jump of {(ratio - 1.0)*100:.1f}% on {d} linked to unverified {ca_type}"
                    rcode = ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED
                else:
                    exp_text = f"Extreme unexplained price jump of {(ratio - 1.0)*100:.1f}% on {d} (violates exchange circuit bounds)"
                    rcode = ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT

                anomalies.append(AnomalyEvent(
                    symbol=sym_clean,
                    date=d,
                    anomaly_type="STRUCTURAL_PRICE_JUMP",
                    price_ratio=round(ratio, 4),
                    volume_multiple=1.0,
                    is_explained=is_exp,
                    explanation=exp_text,
                    severity="WARN" if is_exp else "FAIL",
                    reason_code=rcode,
                    event_type=ca_type,
                ))

            # Discontinuity Check 3: Overnight Structural Gap (open gap >= 40% with persistent close move >= 35%)
            elif open_gap >= self.config.structural_gap_threshold and ret_abs >= 0.35:
                if not ca or not ca.get("is_resolved"):
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=d,
                        anomaly_type="STRUCTURAL_OVERNIGHT_GAP",
                        price_ratio=round(ratio, 4),
                        volume_multiple=1.0,
                        is_explained=False,
                        explanation=f"Overnight structural open gap of {open_gap*100:.1f}% on {d} with persistent dislocation",
                        severity="FAIL",
                        reason_code=ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT,
                        event_type=ca_type,
                    ))

            # Discontinuity Check 4: Statistical Outlier (ret >= 35% and ret > 6 * hist_std)
            elif ret_abs >= 0.35 and ret_abs > (self.config.statistical_anomaly_sigma * hist_std):
                if not ca or not ca.get("is_resolved"):
                    anomalies.append(AnomalyEvent(
                        symbol=sym_clean,
                        date=d,
                        anomaly_type="STATISTICAL_RETURN_ANOMALY",
                        price_ratio=round(ratio, 4),
                        volume_multiple=1.0,
                        is_explained=False,
                        explanation=f"Statistical return dislocation of {ret_abs*100:.1f}% on {d} (>6 sigma of {hist_std*100:.2f}%)",
                        severity="FAIL",
                        reason_code=ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT,
                        event_type=ca_type,
                    ))

        # --- GATE 3: Cumulative Return Distortion Gate ---
        # If Ret_252 > 300% (+3.0) and there is any single-day jump > 50% in the window
        lookback_start = max(0, len(closes) - min(252, len(closes)))
        window_closes = closes[lookback_start:]
        if len(window_closes) >= 2:
            ret_252 = (window_closes[-1] / window_closes[0]) - 1.0
            if ret_252 > 3.0:
                # Check if this 300% move was driven by a single-day structural jump >= 50%
                window_ratios = window_closes[1:] / window_closes[:-1]
                if (window_ratios >= 1.50).any():
                    jump_idx = int(np.where(window_ratios >= 1.50)[0][0])
                    jump_date = str(dates[lookback_start + 1 + jump_idx])
                    ca = self._action_lookup.get((sym_clean, jump_date))
                    if not ca or not ca.get("is_resolved"):
                        anomalies.append(AnomalyEvent(
                            symbol=sym_clean,
                            date=as_of_clean,
                            anomaly_type="ARTIFICIAL_RETURN_DISTORTION",
                            price_ratio=round(ret_252 + 1.0, 2),
                            volume_multiple=1.0,
                            is_explained=False,
                            explanation=f"1Y return of {ret_252*100:.1f}% contaminated by unverified single-session jump on {jump_date}",
                            severity="FAIL",
                            reason_code=ScannerReasonCode.UNRESOLVED_STRUCTURAL_PRICE_EVENT,
                            event_type="ARTIFICIAL_RETURN",
                        ))

        return anomalies

    def is_security_clean(
        self,
        symbol: str,
        df: pd.DataFrame,
        as_of_date: str,
    ) -> Tuple[bool, Optional[AnomalyEvent]]:
        """
        Convenience gate: Returns (True, None) if clean, or (False, first_blocking_anomaly).
        """
        anomalies = self.detect_anomalies(symbol, df, as_of_date)
        for a in anomalies:
            if not a.is_explained and a.severity == "FAIL":
                return False, a
        return True, None
