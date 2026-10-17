"""
pydroid_core/analytical_price.py
Authoritative Corporate-Action-Aware Analytical Price Engine for Project MIP Pydroid3.

Three-Tier Data Architecture:
  1. RAW_MARKET_PRICE: Pure exchange transaction records (data/universe.db, immutable).
  2. CORPORATE_ACTION_REGISTRY: Point-in-time verified event metadata (data/corporate_actions_registry.json).
  3. ADJUSTED_ANALYTICAL_PRICE: Dynamically derived analytical OHLCV series for feature generation.

Taxonomy Treatments:
  - ENTERPRISE_PRESERVING (BONUS, SPLIT, CONSOLIDATION): Continuous backward factor adjustment.
  - ENTERPRISE_ALTERING (DEMERGER, SPIN_OFF, MERGER): Boundary history partitioning.
  - GENUINE_MARKET_EVENT: Retained unmodified in raw series.
  - UNRESOLVED STRUCTURAL DROP: Fail closed / quarantine.
"""

from dataclasses import dataclass, asdict
from enum import Enum
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Union
import numpy as np
import pandas as pd

from .data_engine import get_base_dir


class ActionNature(str, Enum):
    """Semantic nature of corporate action relative to enterprise boundary."""
    ENTERPRISE_PRESERVING = "ENTERPRISE_PRESERVING"
    ENTERPRISE_ALTERING = "ENTERPRISE_ALTERING"
    MARKET_EVENT = "MARKET_EVENT"
    UNKNOWN = "UNKNOWN"


class ActionType(str, Enum):
    """Institutional taxonomy of corporate event types."""
    SPLIT = "SPLIT"
    BONUS = "BONUS"
    CONSOLIDATION = "CONSOLIDATION"
    DEMERGER = "DEMERGER"
    SPIN_OFF = "SPIN_OFF"
    MERGER = "MERGER"
    AMALGAMATION = "AMALGAMATION"
    CAPITAL_REDUCTION = "CAPITAL_REDUCTION"
    SCHEME_OF_ARRANGEMENT = "SCHEME_OF_ARRANGEMENT"
    TICKER_CHANGE = "TICKER_CHANGE"
    GENUINE_CRASH = "GENUINE_CRASH"
    DATA_CORRUPTION = "DATA_CORRUPTION"
    UNKNOWN_MATERIAL_EVENT = "UNKNOWN_MATERIAL_EVENT"


@dataclass
class CorporateActionEvent:
    """Immutable point-in-time representation of a corporate action."""
    symbol: str
    security_id: str
    ex_date: str
    record_date: str
    effective_date: str
    action_type: ActionType
    action_nature: ActionNature
    factor: float
    resulting_entities: List[str]
    source_authority: str
    source_reference: str
    ingestion_timestamp: str
    is_resolved: bool = True
    status: str = "CONFIRMED"
    notes: Optional[str] = None

    @property
    def adjustment_factor(self) -> float:
        """Institutional alias for backward adjustment factor."""
        return float(self.factor)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["action_type"] = self.action_type.value
        d["action_nature"] = self.action_nature.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CorporateActionEvent":
        act_t = data.get("action_type", "UNKNOWN_MATERIAL_EVENT")
        act_n = data.get("action_nature", "UNKNOWN")
        
        # Safe Enum casting
        try:
            parsed_type = ActionType(act_t)
        except ValueError:
            parsed_type = ActionType.UNKNOWN_MATERIAL_EVENT
            
        try:
            parsed_nature = ActionNature(act_n)
        except ValueError:
            parsed_nature = ActionNature.UNKNOWN
            
        return cls(
            symbol=str(data.get("symbol", "")).strip().upper(),
            security_id=str(data.get("security_id", "")),
            ex_date=str(data.get("ex_date", ""))[:10],
            record_date=str(data.get("record_date", ""))[:10],
            effective_date=str(data.get("effective_date", data.get("ex_date", "")))[:10],
            action_type=parsed_type,
            action_nature=parsed_nature,
            factor=float(data.get("factor", 1.0)),
            resulting_entities=list(data.get("resulting_entities", [])),
            source_authority=str(data.get("source_authority", "")),
            source_reference=str(data.get("source_reference", "")),
            ingestion_timestamp=str(data.get("ingestion_timestamp", "")),
            is_resolved=bool(data.get("is_resolved", True)),
            status=str(data.get("status", "CONFIRMED")),
            notes=data.get("notes")
        )


class AnalyticalPriceEngine:
    """
    Point-in-Time Corporate-Action-Aware Analytical Data Layer.
    Guarantees:
      - Raw database remains 100% immutable and unedited.
      - Future corporate actions are strictly invisible prior to effective dates.
      - Enterprise-preserving events (splits/bonuses) maintain continuous price momentum.
      - Enterprise-altering events (demergers) sever pre-reorganization history cleanly.
      - Unexplained structural drops > 40% fail closed without contaminating the scanner.
    """

    def __init__(self, registry_path: Optional[Union[Path, str]] = None):
        base_dir = get_base_dir()
        self.registry_path = Path(registry_path) if registry_path else (base_dir / "data" / "corporate_actions_registry.json")
        self.actions_by_symbol: Dict[str, List[CorporateActionEvent]] = {}
        self.reload_registry()

    def reload_registry(self) -> None:
        """Loads and indexes the sidecar corporate action registry."""
        self.actions_by_symbol.clear()
        if not self.registry_path.exists():
            return

        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # Support both list of actions and wrapped dictionary
            action_list = data.get("actions", data) if isinstance(data, dict) else data
            
            for item in action_list:
                ev = CorporateActionEvent.from_dict(item)
                if ev.symbol not in self.actions_by_symbol:
                    self.actions_by_symbol[ev.symbol] = []
                self.actions_by_symbol[ev.symbol].append(ev)
                
            # Sort each symbol's actions chronologically
            for sym in self.actions_by_symbol:
                self.actions_by_symbol[sym].sort(key=lambda a: a.ex_date)
        except Exception:
            self.actions_by_symbol.clear()

    def get_active_actions(self, symbol: str, as_of_date: str) -> List[CorporateActionEvent]:
        """
        Point-In-Time Enforcer:
        Returns only corporate actions effective on or before as_of_date.
        Future corporate actions are strictly invisible.
        """
        sym_clean = str(symbol).strip().upper()
        as_of_clean = str(as_of_date).strip()[:10]
        
        all_actions = self.actions_by_symbol.get(sym_clean, [])
        active: List[CorporateActionEvent] = []
        for a in all_actions:
            # Enforce temporal boundary: on or after ex_date, exchange pricing reflects corporate action
            if a.ex_date <= as_of_clean:
                active.append(a)
        return active

    def derive_analytical_series(
        self,
        symbol: str,
        df_raw: pd.DataFrame,
        as_of_date: str,
        min_clean_bars: int = 252,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Derives analytical OHLCV price series for a security:
          - Applies boundary history partitioning for enterprise-altering reorganizations.
          - Applies continuous backward factor adjustment for enterprise-preserving actions.
          - Quarantines unexplained dislocations > 40%.
        """
        sym_clean = str(symbol).strip().upper()
        as_of_clean = str(as_of_date).strip()[:10]

        diag: Dict[str, Any] = {
            "symbol": sym_clean,
            "as_of_date": as_of_clean,
            "raw_bars_count": len(df_raw) if df_raw is not None else 0,
            "actions_applied": 0,
            "treatment": "RAW_CONTINUOUS",
            "is_partitioned": False,
            "partition_cutoff": None,
            "clean_bars_count": 0,
            "is_blocked_unresolved": False,
            "unresolved_reason": None,
        }

        if df_raw is None or df_raw.empty:
            diag["clean_bars_count"] = 0
            return pd.DataFrame(), diag

        # 1. Enforce PIT date cutoff on market data
        df = df_raw.copy()
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).str.strip().str[:10]
            df = df[df["date"] <= as_of_clean].sort_values("date").reset_index(drop=True)
        else:
            return df, diag

        if df.empty:
            diag["clean_bars_count"] = 0
            return df, diag

        diag["clean_bars_count"] = len(df)

        # 2. Retrieve Point-In-Time Active Actions
        actions = self.get_active_actions(sym_clean, as_of_clean)
        diag["actions_applied"] = len(actions)

        # -------------------------------------------------------------
        # Branch A: Enterprise-Altering Reorganizations (Demergers, etc.)
        # -------------------------------------------------------------
        altering_actions = [a for a in actions if a.action_nature == ActionNature.ENTERPRISE_ALTERING]
        if altering_actions:
            # Locate latest reorganization ex-date
            latest_reorg = max(altering_actions, key=lambda a: a.ex_date)
            cutoff = latest_reorg.ex_date
            
            # Boundary History Partitioning: Sever pre-reorganization conglomerate bars
            df_part = df[df["date"] >= cutoff].copy().reset_index(drop=True)
            diag["treatment"] = "BOUNDARY_HISTORY_PARTITIONING"
            diag["is_partitioned"] = True
            diag["partition_cutoff"] = cutoff
            diag["clean_bars_count"] = len(df_part)
            
            # History qualification evaluated downstream by validator (min_history_bars)
            return df_part, diag

        # -------------------------------------------------------------
        # Branch B: Enterprise-Preserving Actions (Bonus, Split)
        # -------------------------------------------------------------
        preserving_actions = [a for a in actions if a.action_nature == ActionNature.ENTERPRISE_PRESERVING]
        if preserving_actions:
            df_adj = df.copy()
            diag["treatment"] = "CONTINUOUS_BACKWARD_ADJUSTMENT"
            
            # Apply multiplicative scaling in reverse chronological order
            for act in sorted(preserving_actions, key=lambda a: a.ex_date, reverse=True):
                mask = df_adj["date"] < act.ex_date
                factor = act.factor
                if factor > 0:
                    for col in ["open", "high", "low", "close"]:
                        if col in df_adj.columns:
                            df_adj.loc[mask, col] *= factor
                    if "volume" in df_adj.columns:
                        df_adj.loc[mask, "volume"] /= factor

            # Verify dislocation at ex-date transition is resolved
            df_adj["_ratio"] = df_adj["close"] / df_adj["close"].shift(1)
            for act in preserving_actions:
                act_rows = df_adj[df_adj["date"] == act.ex_date]
                if not act_rows.empty and float(act_rows["_ratio"].iloc[0]) <= 0.60:
                    diag["is_blocked_unresolved"] = True
                    diag["unresolved_reason"] = f"Residual dislocation for {act.symbol} on {act.ex_date} after factor adjustment"
                    return df_adj.drop(columns=["_ratio"], errors="ignore"), diag

            # Check active lookback window for any unexplained drops
            active_tail = df_adj.tail(min_clean_bars)
            bad_drops = active_tail[active_tail["_ratio"] <= 0.60]
            if not bad_drops.empty:
                diag["is_blocked_unresolved"] = True
                diag["unresolved_reason"] = f"Unresolved structural drop in lookback window on {bad_drops['date'].iloc[0]}"
                return df_adj.drop(columns=["_ratio"], errors="ignore"), diag

            return df_adj.drop(columns=["_ratio"], errors="ignore"), diag

        # -------------------------------------------------------------
        # Branch C: No Actions (Normal Market Series / Anomaly Check)
        # -------------------------------------------------------------
        if len(df) >= 2:
            df["_ratio"] = df["close"] / df["close"].shift(1)
            active_tail = df.tail(min_clean_bars)
            bad_drops = active_tail[active_tail["_ratio"] <= 0.60]
            if not bad_drops.empty:
                # Structural price drop > 40% with no corporate action record -> Fail Closed
                diag["treatment"] = "UNRESOLVED_CRASH"
                diag["is_blocked_unresolved"] = True
                diag["unresolved_reason"] = f"Unresolved structural drop of {(1.0 - bad_drops['_ratio'].iloc[0])*100:.1f}% on {bad_drops['date'].iloc[0]}"
                return df.drop(columns=["_ratio"], errors="ignore"), diag
            df = df.drop(columns=["_ratio"], errors="ignore")

        return df, diag
