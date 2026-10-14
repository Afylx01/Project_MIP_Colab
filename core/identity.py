"""
pydroid_core/identity.py
Security Identity & Ticker Transition Governance Engine for Project MIP Pydroid3.
Resolves volatile stock exchange ticker symbols to immutable canonical security identifiers.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import datetime
import pandas as pd


@dataclass
class TickerAlias:
    """Historical ticker symbol mapped to canonical security identity."""
    symbol: str
    exchange: str
    valid_from: str       # YYYY-MM-DD
    valid_to: str         # YYYY-MM-DD (or '9999-12-31' for active)


@dataclass
class SecurityIdentity:
    """Canonical representation of an equity security entity."""
    security_id: str
    canonical_name: str
    isin: Optional[str] = None
    aliases: List[TickerAlias] = field(default_factory=list)


# Known institutional NSE ticker changes ledger
DEFAULT_TICKER_CHANGES = [
    {"security_id": "SEC_M_M", "old_symbol": "MM", "new_symbol": "M&M", "effective_date": "2018-01-01"},
    {"security_id": "SEC_LTI_MINDTREE", "old_symbol": "LTI", "new_symbol": "LTIM", "effective_date": "2022-11-24"},
    {"security_id": "SEC_LTI_MINDTREE", "old_symbol": "MINDTREE", "new_symbol": "LTIM", "effective_date": "2022-11-24"},
    {"security_id": "SEC_TATA_MOTORS", "old_symbol": "TATAMTRDVR", "new_symbol": "TATAMOTORS", "effective_date": "2024-09-01"},
    {"security_id": "SEC_CADILA", "old_symbol": "CADILAHC", "new_symbol": "ZYDUSLIFE", "effective_date": "2022-03-07"},
    {"security_id": "SEC_PIRAMAL", "old_symbol": "PEL", "new_symbol": "PIRAMALENT", "effective_date": "2022-10-19"},
    {"security_id": "SEC_ADANI_TOTAL", "old_symbol": "ADANIGAS", "new_symbol": "ATGL", "effective_date": "2021-01-01"},
]


class SecurityIdentityManager:
    """
    Manages security identity mapping, ticker renames, mergers, and symbol transitions.
    Prevents artificial return spikes and duplicate securities in portfolio.
    """

    def __init__(self):
        self._registry: Dict[str, SecurityIdentity] = {}
        self._symbol_lookup: Dict[str, List[Tuple[str, str, str]]] = {}
        self._initialize_default_registry()

    def _initialize_default_registry(self):
        """Initializes known NSE symbol mappings."""
        for chg in DEFAULT_TICKER_CHANGES:
            sec_id = chg["security_id"]
            eff = chg["effective_date"]
            self.register_ticker_change(
                security_id=sec_id,
                old_symbol=chg["old_symbol"],
                new_symbol=chg["new_symbol"],
                effective_date=eff,
                canonical_name=sec_id.replace("SEC_", "")
            )

    def register_ticker_change(
        self,
        security_id: str,
        old_symbol: str,
        new_symbol: str,
        effective_date: str,
        canonical_name: Optional[str] = None,
        exchange: str = "NSE"
    ):
        """Registers a verified corporate ticker rename or merger."""
        old_sym = str(old_symbol).strip().upper()
        new_sym = str(new_symbol).strip().upper()
        eff_date = str(effective_date).strip()[:10]

        if security_id not in self._registry:
            self._registry[security_id] = SecurityIdentity(
                security_id=security_id,
                canonical_name=canonical_name or security_id,
            )

        identity = self._registry[security_id]
        identity.aliases.append(TickerAlias(
            symbol=old_sym,
            exchange=exchange,
            valid_from="1990-01-01",
            valid_to=eff_date
        ))
        identity.aliases.append(TickerAlias(
            symbol=new_sym,
            exchange=exchange,
            valid_from=eff_date,
            valid_to="9999-12-31"
        ))

        if old_sym not in self._symbol_lookup:
            self._symbol_lookup[old_sym] = []
        self._symbol_lookup[old_sym].append((security_id, "1990-01-01", eff_date))

        if new_sym not in self._symbol_lookup:
            self._symbol_lookup[new_sym] = []
        self._symbol_lookup[new_sym].append((security_id, eff_date, "9999-12-31"))

    def resolve_security_id(self, symbol: str, as_of_date: Optional[str] = None) -> str:
        """
        Resolves a ticker symbol to its canonical security_id as of a given date.
        If no explicit mapping exists, creates a deterministic canonical ID.
        """
        sym_clean = str(symbol).strip().upper()
        date_clean = str(as_of_date).strip()[:10] if as_of_date else "9999-12-31"

        if sym_clean in self._symbol_lookup:
            for sec_id, v_from, v_to in self._symbol_lookup[sym_clean]:
                if v_from <= date_clean <= v_to:
                    return sec_id
            return self._symbol_lookup[sym_clean][-1][0]

        return f"SEC_{sym_clean}"

    def stitch_symbol_bars(
        self,
        security_id: str,
        bars_by_symbol: Dict[str, pd.DataFrame],
        as_of_date: str,
    ) -> pd.DataFrame:
        """
        Stitches historical bars across ticker transitions into a single unified
        chronological price series under the canonical security_id.
        Prevents ticker changes from wiping out 252-day momentum lookback.
        """
        as_of_clean = str(as_of_date).strip()[:10]
        identity = self._registry.get(security_id)
        if not identity:
            for sym, df in bars_by_symbol.items():
                if f"SEC_{sym}" == security_id:
                    df_out = df.copy()
                    df_out["security_id"] = security_id
                    return df_out[df_out["date"] <= as_of_clean].sort_values("date").reset_index(drop=True)
            return pd.DataFrame()

        collected = []
        for alias in identity.aliases:
            sym = alias.symbol
            if sym in bars_by_symbol:
                df_sub = bars_by_symbol[sym].copy()
                mask = (df_sub["date"] >= alias.valid_from) & (df_sub["date"] <= alias.valid_to) & (df_sub["date"] <= as_of_clean)
                df_valid = df_sub[mask].copy()
                if not df_valid.empty:
                    collected.append(df_valid)

        if not collected:
            return pd.DataFrame()

        merged = pd.concat(collected, ignore_index=True)
        merged = merged.drop_duplicates(subset=["date"], keep="last")
        merged = merged.sort_values("date").reset_index(drop=True)
        merged["security_id"] = security_id
        return merged
