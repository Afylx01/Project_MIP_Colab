"""
MIP Android — Scanner Hardening & Constituent Reconciliation Engine
Directive: ORDER 033 — Scanner Hardening and End-to-End Verification

Provides robust constituent management, official NIFTY source validation,
change detection, freshness policy, database-universe reconciliation,
and safe incremental market-data refresh while preserving the frozen strategy.
"""

import os
import sys
import io
import csv
import json
import time
import shutil
import hashlib
import sqlite3
import datetime
import urllib.request
import urllib.error
import ssl
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any
from enum import Enum
from dataclasses import dataclass, field, asdict

import pandas as pd
import numpy as np

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_engine import (
    get_base_dir,
    get_db_path,
    get_connection,
    get_latest_date,
    load_trading_calendar,
    load_bars,
    load_symbol_sector_map,
    get_universe_label,
    KNOWN_NSE_HOLIDAYS,
)
from core.scanner import PydroidScanner, format_screener_tearsheet
from core.config import MIPScannerConfig
from core.reason_codes import ScannerReasonCode
from core.auto_fetch import PydroidAutoFetch, AutoFetchStatus

_COLAB_DOWNLOAD_REGISTRY: Dict[str, float] = {}

def trigger_colab_download(file_path: Any, cooldown_seconds: float = 15.0) -> bool:
    """
    Safely triggers google.colab.files.download with strict deduplication and cooldown.
    Guarantees that the exact same file is never downloaded more than once within cooldown period.
    """
    global _COLAB_DOWNLOAD_REGISTRY
    if not file_path:
        return False
    p_str = str(Path(file_path).resolve())
    now = time.time()
    last_time = _COLAB_DOWNLOAD_REGISTRY.get(p_str, 0.0)
    if (now - last_time) < cooldown_seconds:
        return False
    _COLAB_DOWNLOAD_REGISTRY[p_str] = now
    try:
        from google.colab import files
        files.download(p_str)
        return True
    except Exception:
        return False


class ConstituentSourceStatus(str, Enum):
    LIVE_VERIFIED = "LIVE-VERIFIED"
    CACHED_VALID = "CACHED-VALID"
    STALE = "STALE"
    BLOCKED = "BLOCKED"
    SIMULATED_TEST_FIXTURE = "SIMULATED_TEST_FIXTURE"


class SymbolDataStatus(str, Enum):
    PRESENT_CURRENT = "PRESENT_CURRENT"
    PRESENT_STALE = "PRESENT_STALE"
    MISSING = "MISSING"
    INVALID = "INVALID"
    UNRESOLVED_MAPPING = "UNRESOLVED_MAPPING"


@dataclass
class ConstituentValidationResult:
    is_valid: bool
    status_code: int
    error_message: str = ""
    raw_row_count: int = 0
    valid_symbols: Set[str] = field(default_factory=set)
    symbol_metadata: Dict[str, Dict[str, str]] = field(default_factory=dict)
    duplicate_symbols: List[str] = field(default_factory=list)
    sha256_hash: str = ""

    @property
    def row_count(self) -> int:
        return self.raw_row_count



@dataclass
class ConstituentReconciliationReport:
    universe_name: str
    source_status: ConstituentSourceStatus
    source_url: str
    snapshot_date: str
    snapshot_sha256: str
    total_constituents: int
    added_symbols: List[str] = field(default_factory=list)
    removed_symbols: List[str] = field(default_factory=list)
    unchanged_symbols: List[str] = field(default_factory=list)
    is_changed_from_previous: bool = False
    warning_message: str = ""

    @property
    def valid_symbols(self) -> Set[str]:
        return set(self.added_symbols).union(set(self.unchanged_symbols))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "universe_name": self.universe_name,
            "source_status": self.source_status.value,
            "source_url": self.source_url,
            "snapshot_date": self.snapshot_date,
            "snapshot_sha256": self.snapshot_sha256,
            "total_constituents": self.total_constituents,
            "added_count": len(self.added_symbols),
            "removed_count": len(self.removed_symbols),
            "unchanged_count": len(self.unchanged_symbols),
            "is_changed_from_previous": self.is_changed_from_previous,
            "added_symbols": sorted(self.added_symbols),
            "removed_symbols": sorted(self.removed_symbols),
            "warning_message": self.warning_message,
        }


@dataclass
class MarketDataReconciliationReport:
    as_of_date: str
    total_constituents: int
    present_current_count: int = 0
    present_stale_count: int = 0
    missing_count: int = 0
    invalid_count: int = 0
    unresolved_mapping_count: int = 0
    present_current_symbols: List[str] = field(default_factory=list)
    present_stale_details: Dict[str, int] = field(default_factory=dict)  # sym -> sessions behind
    missing_symbols: List[str] = field(default_factory=list)
    invalid_symbols: List[str] = field(default_factory=list)
    coverage_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of_date": self.as_of_date,
            "total_constituents": self.total_constituents,
            "present_current_count": self.present_current_count,
            "present_stale_count": self.present_stale_count,
            "missing_count": self.missing_count,
            "invalid_count": self.invalid_count,
            "unresolved_mapping_count": self.unresolved_mapping_count,
            "coverage_pct": round(self.coverage_pct, 2),
            "missing_symbols": sorted(self.missing_symbols),
            "stale_symbols_count": len(self.present_stale_details),
        }


NIFTY_INDICES_CATALOG = {
    # Broad Market Indices (15)
    "NIFTY50": {
        "name": "NIFTY 50",
        "category": "Broad Market",
        "filename": "ind_nifty50list.csv",
        "row_bounds": (45, 55),
        "aliases": ["NIFTY50", "NIFTY 50", "50"],
    },
    "NIFTYNEXT50": {
        "name": "NIFTY Next 50",
        "category": "Broad Market",
        "filename": "ind_niftynext50list.csv",
        "row_bounds": (45, 55),
        "aliases": ["NIFTYNEXT50", "NIFTY NEXT 50", "NEXT50", "JUNIORBEES"],
    },
    "NIFTY100": {
        "name": "NIFTY 100",
        "category": "Broad Market",
        "filename": "ind_nifty100list.csv",
        "row_bounds": (95, 105),
        "aliases": ["NIFTY100", "NIFTY 100", "100"],
    },
    "NIFTY200": {
        "name": "NIFTY 200",
        "category": "Broad Market",
        "filename": "ind_nifty200list.csv",
        "row_bounds": (190, 210),
        "aliases": ["NIFTY200", "NIFTY 200", "200"],
    },
    "NIFTY500": {
        "name": "NIFTY 500",
        "category": "Broad Market",
        "filename": "ind_nifty500list.csv",
        "row_bounds": (490, 515),
        "aliases": ["NIFTY500", "NIFTY 500", "500"],
    },
    "NIFTY750": {
        "name": "NIFTY Total Market",
        "category": "Broad Market",
        "filename": "ind_niftytotalmarket_list.csv",
        "row_bounds": (735, 775),
        "aliases": ["NIFTY750", "NIFTY 750", "750", "TOTALMARKET", "NIFTYTOTALMARKET", "NIFTY TOTAL MARKET", "TOTAL_MARKET"],
    },
    "NIFTYMIDCAP50": {
        "name": "NIFTY Midcap 50",
        "category": "Broad Market",
        "filename": "ind_niftymidcap50list.csv",
        "row_bounds": (45, 55),
        "aliases": ["NIFTYMIDCAP50", "NIFTY MIDCAP 50", "MIDCAP50"],
    },
    "NIFTYMIDCAP100": {
        "name": "NIFTY Midcap 100",
        "category": "Broad Market",
        "filename": "ind_niftymidcap100list.csv",
        "row_bounds": (95, 105),
        "aliases": ["NIFTYMIDCAP100", "NIFTY MIDCAP 100", "MIDCAP100"],
    },
    "NIFTYMIDCAP150": {
        "name": "NIFTY Midcap 150",
        "category": "Broad Market",
        "filename": "ind_niftymidcap150list.csv",
        "row_bounds": (140, 160),
        "aliases": ["NIFTYMIDCAP150", "NIFTY MIDCAP 150", "MIDCAP150"],
    },
    "NIFTYSMALLCAP50": {
        "name": "NIFTY Smallcap 50",
        "category": "Broad Market",
        "filename": "ind_niftysmallcap50list.csv",
        "row_bounds": (45, 55),
        "aliases": ["NIFTYSMALLCAP50", "NIFTY SMALLCAP 50", "SMALLCAP50"],
    },
    "NIFTYSMALLCAP100": {
        "name": "NIFTY Smallcap 100",
        "category": "Broad Market",
        "filename": "ind_niftysmallcap100list.csv",
        "row_bounds": (95, 105),
        "aliases": ["NIFTYSMALLCAP100", "NIFTY SMALLCAP 100", "SMALLCAP100"],
    },
    "NIFTYSMALLCAP250": {
        "name": "NIFTY Smallcap 250",
        "category": "Broad Market",
        "filename": "ind_niftysmallcap250list.csv",
        "row_bounds": (240, 260),
        "aliases": ["NIFTYSMALLCAP250", "NIFTY SMALLCAP 250", "SMALLCAP250"],
    },
    "NIFTYMICROCAP250": {
        "name": "NIFTY Microcap 250",
        "category": "Broad Market",
        "filename": "ind_niftymicrocap250_list.csv",
        "row_bounds": (240, 265),
        "aliases": ["NIFTYMICROCAP250", "NIFTY MICROCAP 250", "MICROCAP250", "MICROCAP"],
    },
    "NIFTYMIDSMALLCAP400": {
        "name": "NIFTY MidSmallcap 400",
        "category": "Broad Market",
        "filename": "ind_niftymidsmallcap400list.csv",
        "row_bounds": (385, 415),
        "aliases": ["NIFTYMIDSMALLCAP400", "NIFTY MIDSMALLCAP 400", "MIDSMALLCAP400"],
    },
    "NIFTYLARGEMIDCAP250": {
        "name": "NIFTY LargeMidcap 250",
        "category": "Broad Market",
        "filename": "ind_niftylargemidcap250list.csv",
        "row_bounds": (240, 260),
        "aliases": ["NIFTYLARGEMIDCAP250", "NIFTY LARGEMIDCAP 250", "LARGEMIDCAP250"],
    },

    # Sectoral Indices (14)
    "NIFTYAUTO": {
        "name": "NIFTY Auto",
        "category": "Sectoral",
        "filename": "ind_niftyautolist.csv",
        "row_bounds": (10, 25),
        "aliases": ["NIFTYAUTO", "NIFTY AUTO", "AUTO"],
    },
    "NIFTYBANK": {
        "name": "NIFTY Bank",
        "category": "Sectoral",
        "filename": "ind_niftybanklist.csv",
        "row_bounds": (10, 20),
        "aliases": ["NIFTYBANK", "NIFTY BANK", "BANK", "BANKNIFTY"],
    },
    "NIFTYFINANCIALSERVICES": {
        "name": "NIFTY Financial Services",
        "category": "Sectoral",
        "filename": "ind_niftyfinancelist.csv",
        "row_bounds": (15, 25),
        "aliases": ["NIFTYFINANCIALSERVICES", "NIFTY FINANCIAL SERVICES", "FINANCIALSERVICES", "FINNIFTY", "NIFTYFINANCE"],
    },
    "NIFTYFMCG": {
        "name": "NIFTY FMCG",
        "category": "Sectoral",
        "filename": "ind_niftyfmcglist.csv",
        "row_bounds": (10, 25),
        "aliases": ["NIFTYFMCG", "NIFTY FMCG", "FMCG"],
    },
    "NIFTYIT": {
        "name": "NIFTY IT",
        "category": "Sectoral",
        "filename": "ind_niftyitlist.csv",
        "row_bounds": (8, 15),
        "aliases": ["NIFTYIT", "NIFTY IT", "IT"],
    },
    "NIFTYMEDIA": {
        "name": "NIFTY Media",
        "category": "Sectoral",
        "filename": "ind_niftymedialist.csv",
        "row_bounds": (8, 15),
        "aliases": ["NIFTYMEDIA", "NIFTY MEDIA", "MEDIA"],
    },
    "NIFTYMETAL": {
        "name": "NIFTY Metal",
        "category": "Sectoral",
        "filename": "ind_niftymetallist.csv",
        "row_bounds": (10, 25),
        "aliases": ["NIFTYMETAL", "NIFTY METAL", "METAL"],
    },
    "NIFTYPHARMA": {
        "name": "NIFTY Pharma",
        "category": "Sectoral",
        "filename": "ind_niftypharmalist.csv",
        "row_bounds": (15, 25),
        "aliases": ["NIFTYPHARMA", "NIFTY PHARMA", "PHARMA"],
    },
    "NIFTYPSUBANK": {
        "name": "NIFTY PSU Bank",
        "category": "Sectoral",
        "filename": "ind_niftypsubanklist.csv",
        "row_bounds": (8, 20),
        "aliases": ["NIFTYPSUBANK", "NIFTY PSU BANK", "PSUBANK"],
    },
    "NIFTYPRIVATEBANK": {
        "name": "NIFTY Private Bank",
        "category": "Sectoral",
        "filename": "ind_nifty_privatebanklist.csv",
        "row_bounds": (8, 15),
        "aliases": ["NIFTYPRIVATEBANK", "NIFTY PRIVATE BANK", "PRIVATEBANK"],
    },
    "NIFTYREALTY": {
        "name": "NIFTY Realty",
        "category": "Sectoral",
        "filename": "ind_niftyrealtylist.csv",
        "row_bounds": (8, 15),
        "aliases": ["NIFTYREALTY", "NIFTY REALTY", "REALTY"],
    },
    "NIFTYHEALTHCARE": {
        "name": "NIFTY Healthcare",
        "category": "Sectoral",
        "filename": "ind_niftyhealthcarelist.csv",
        "row_bounds": (15, 25),
        "aliases": ["NIFTYHEALTHCARE", "NIFTY HEALTHCARE", "HEALTHCARE"],
    },
    "NIFTYCONSUMERDURABLES": {
        "name": "NIFTY Consumer Durables",
        "category": "Sectoral",
        "filename": "ind_niftyconsumerdurableslist.csv",
        "row_bounds": (10, 25),
        "aliases": ["NIFTYCONSUMERDURABLES", "NIFTY CONSUMER DURABLES", "CONSUMERDURABLES"],
    },
    "NIFTYOILGAS": {
        "name": "NIFTY Oil & Gas",
        "category": "Sectoral",
        "filename": "ind_niftyoilgaslist.csv",
        "row_bounds": (10, 25),
        "aliases": ["NIFTYOILGAS", "NIFTY OIL & GAS", "NIFTY OIL AND GAS", "OILGAS", "OILANDGAS"],
    },

    # Thematic / Strategy Indices (7)
    "NIFTYCOMMODITIES": {
        "name": "NIFTY Commodities",
        "category": "Thematic",
        "filename": "ind_niftycommoditieslist.csv",
        "row_bounds": (25, 35),
        "aliases": ["NIFTYCOMMODITIES", "NIFTY COMMODITIES", "COMMODITIES"],
    },
    "NIFTYENERGY": {
        "name": "NIFTY Energy",
        "category": "Thematic",
        "filename": "ind_niftyenergylist.csv",
        "row_bounds": (35, 45),
        "aliases": ["NIFTYENERGY", "NIFTY ENERGY", "ENERGY"],
    },
    "NIFTYINFRASTRUCTURE": {
        "name": "NIFTY Infrastructure",
        "category": "Thematic",
        "filename": "ind_niftyinfralist.csv",
        "row_bounds": (25, 35),
        "aliases": ["NIFTYINFRASTRUCTURE", "NIFTY INFRASTRUCTURE", "INFRASTRUCTURE", "INFRA", "NIFTYINFRA"],
    },
    "NIFTYCPSE": {
        "name": "NIFTY CPSE",
        "category": "Thematic",
        "filename": "ind_niftycpselist.csv",
        "row_bounds": (10, 18),
        "aliases": ["NIFTYCPSE", "NIFTY CPSE", "CPSE"],
    },
    "NIFTYPSE": {
        "name": "NIFTY PSE",
        "category": "Thematic",
        "filename": "ind_niftypselist.csv",
        "row_bounds": (15, 25),
        "aliases": ["NIFTYPSE", "NIFTY PSE", "PSE"],
    },
    "NIFTYSERVICESSECTOR": {
        "name": "NIFTY Services Sector",
        "category": "Thematic",
        "filename": "ind_niftyservicelist.csv",
        "row_bounds": (25, 35),
        "aliases": ["NIFTYSERVICESSECTOR", "NIFTY SERVICES SECTOR", "SERVICESSECTOR", "SERVICES", "NIFTYSERVICES"],
    },
    "NIFTYMNC": {
        "name": "NIFTY MNC",
        "category": "Thematic",
        "filename": "ind_niftymnclist.csv",
        "row_bounds": (25, 35),
        "aliases": ["NIFTYMNC", "NIFTY MNC", "MNC"],
    },
}


def normalize_universe_mode(mode: str) -> str:
    """Normalizes any index mode, ticker alias, or display string to canonical catalog key."""
    cleaned = str(mode).strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    for k, v in NIFTY_INDICES_CATALOG.items():
        if cleaned == k:
            return k
        for alias in v.get("aliases", []):
            if cleaned == alias.replace(" ", "").replace("_", "").replace("-", "").upper():
                return k
    if "750" in cleaned or "TOTAL" in cleaned:
        return "NIFTY750"
    if "500" in cleaned:
        return "NIFTY500"
    return cleaned


def get_hardened_universe_label(universe_mode: str) -> str:
    """Returns human-readable institutional label across all 36 NIFTY indices."""
    u_norm = normalize_universe_mode(universe_mode)
    if u_norm in NIFTY_INDICES_CATALOG:
        return NIFTY_INDICES_CATALOG[u_norm]["name"]
    return get_universe_label(universe_mode)


class ConstituentValidator:
    """Institutional validator for NIFTY Index constituent payloads."""

    REQUIRED_COLUMNS = {"COMPANY NAME", "INDUSTRY", "SYMBOL", "SERIES", "ISIN CODE"}

    ROW_BOUNDS = {k: v["row_bounds"] for k, v in NIFTY_INDICES_CATALOG.items()}
    ROW_BOUNDS["TOTALMARKET"] = (735, 775)

    @classmethod
    def validate_csv_content(cls, content: bytes, universe_key: str = "NIFTY500") -> ConstituentValidationResult:
        if not content:
            return ConstituentValidationResult(
                is_valid=False, status_code=400, error_message="Empty content"
            )

        # Anti-HTML / Anti-Error guard
        text_preview = content[:2000].decode("utf-8", errors="ignore").lower()
        if any(err_term in text_preview for err_term in ["<!doctype html", "<html", "access denied", "403 forbidden", "cloudflare"]):
            return ConstituentValidationResult(
                is_valid=False, status_code=403, error_message="HTML error payload detected"
            )

        if len(content) < 30:
            return ConstituentValidationResult(
                is_valid=False, status_code=400, error_message="Truncated payload (<30 bytes)"
            )

        sha256 = hashlib.sha256(content).hexdigest()

        try:
            df = pd.read_csv(io.BytesIO(content))
        except Exception as e:
            return ConstituentValidationResult(
                is_valid=False, status_code=422, error_message=f"CSV decoding failure: {e}", sha256_hash=sha256
            )

        # Validate header columns
        normalized_cols = {str(c).strip().upper() for c in df.columns}
        missing_cols = cls.REQUIRED_COLUMNS - normalized_cols
        if missing_cols:
            return ConstituentValidationResult(
                is_valid=False,
                status_code=422,
                error_message=f"Missing required constituent header columns: {sorted(list(missing_cols))}",
                sha256_hash=sha256,
            )

        # Row count sanity bounds
        u_norm = normalize_universe_mode(universe_key)
        min_rows, max_rows = cls.ROW_BOUNDS.get(u_norm, (450, 800) if u_norm == "NIFTY500" else (1, 1500))
        if not (min_rows <= len(df) <= max_rows):
            return ConstituentValidationResult(
                is_valid=False,
                status_code=422,
                error_message=f"Constituent row count {len(df)} is outside acceptable bounds [{min_rows}, {max_rows}] for {u_norm}",
                raw_row_count=len(df),
                sha256_hash=sha256,
            )

        sym_col = [c for c in df.columns if str(c).strip().upper() == "SYMBOL"][0]
        ind_col = [c for c in df.columns if str(c).strip().upper() == "INDUSTRY"][0]
        name_col = [c for c in df.columns if str(c).strip().upper() == "COMPANY NAME"][0]
        isin_col = [c for c in df.columns if str(c).strip().upper() == "ISIN CODE"][0]

        valid_symbols = set()
        symbol_meta = {}
        duplicates = []

        for _, row in df.iterrows():
            raw_sym = str(row[sym_col]).strip().upper()
            if not raw_sym or raw_sym == "NAN":
                continue

            # Strict ticker format check: alphanumeric plus allowed characters
            if not raw_sym.replace("-", "").replace("_", "").replace("&", "").isalnum():
                continue

            if raw_sym in valid_symbols:
                duplicates.append(raw_sym)
                continue

            valid_symbols.add(raw_sym)
            symbol_meta[raw_sym] = {
                "symbol": raw_sym,
                "company_name": str(row[name_col]).strip(),
                "industry": str(row[ind_col]).strip(),
                "isin": str(row[isin_col]).strip(),
            }

        if len(valid_symbols) < min_rows:
            return ConstituentValidationResult(
                is_valid=False,
                status_code=422,
                error_message=f"Valid ticker count {len(valid_symbols)} below minimum {min_rows}",
                raw_row_count=len(df),
                duplicate_symbols=duplicates,
                sha256_hash=sha256,
            )

        return ConstituentValidationResult(
            is_valid=True,
            status_code=200,
            raw_row_count=len(df),
            valid_symbols=valid_symbols,
            symbol_metadata=symbol_meta,
            duplicate_symbols=duplicates,
            sha256_hash=sha256,
        )


class ConstituentReconciliationEngine:
    """
    Authoritative index constituent manager.
    Handles source fetching, response validation, change tracking, and freshness policy.
    Supports all 36 official NIFTY indices with 30-day cache refresh TTL.
    """

    OFFICIAL_URLS = {
        k: [
            f"https://www.niftyindices.com/IndexConstituent/{v['filename']}",
            f"https://nsearchives.nseindia.com/content/indices/{v['filename']}",
            f"https://archives.nseindia.com/content/indices/{v['filename']}",
        ]
        for k, v in NIFTY_INDICES_CATALOG.items()
    }

    FILENAME_MAP = {
        k: v["filename"]
        for k, v in NIFTY_INDICES_CATALOG.items()
    }

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.raw_dir = self.base_dir / "data" / "raw_reference"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_file = self.base_dir / "data" / "constituent_snapshots.json"

    def _normalize_mode(self, universe_mode: str) -> str:
        return normalize_universe_mode(universe_mode)

    def _load_previous_snapshot(self, universe_key: str) -> Tuple[Set[str], str]:
        """Loads previous constituent set and SHA-256 fingerprint from snapshot history."""
        if not self.snapshots_file.exists():
            return set(), ""
        try:
            with open(self.snapshots_file, "r", encoding="utf-8") as f:
                history = json.load(f)
            universe_snaps = history.get(universe_key, [])
            if universe_snaps:
                last_snap = universe_snaps[-1]
                return set(last_snap.get("symbols", [])), str(last_snap.get("sha256", ""))
        except Exception:
            pass
        return set(), ""

    def _record_snapshot_idempotent(self, universe_key: str, snap_record: Dict[str, Any]):
        """Persists constituent snapshot idempotently without duplicating identical consecutive runs."""
        history = {}
        if self.snapshots_file.exists():
            try:
                with open(self.snapshots_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except Exception:
                history = {}

        snaps = history.setdefault(universe_key, [])
        if snaps and snaps[-1].get("sha256") == snap_record.get("sha256"):
            # Update last verified timestamp without duplicate entry
            snaps[-1]["last_verified_at"] = datetime.datetime.now().isoformat()
        else:
            snap_record["recorded_at"] = datetime.datetime.now().isoformat()
            snaps.append(snap_record)

        try:
            temp_file = self.snapshots_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(history, f, indent=2)
            temp_file.replace(self.snapshots_file)
        except Exception as e:
            print(f"Warning persisting constituent snapshot: {e}")

    def _fetch_live_with_failover(self, urls: List[str], universe_key: str = "NIFTY500") -> Tuple[Optional[bytes], Optional[str]]:
        """Probes official URLs with failover and validates payload."""
        ctx = ssl.create_default_context()
        for url in urls:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
                        "Accept": "text/csv,application/csv,text/plain",
                    },
                )
                with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                    if resp.status == 200:
                        # Bounded buffer read: Max 10MB to prevent DoS memory exhaustion (OWASP A05 / CWE-400)
                        max_csv_bytes = 10 * 1024 * 1024
                        data = resp.read(max_csv_bytes)
                        val_res = ConstituentValidator.validate_csv_content(data, universe_key=universe_key)
                        if val_res.is_valid:
                            return data, url
            except Exception:
                continue
        return None, None

    def fetch_and_reconcile(
        self,
        universe_mode: str = "NIFTY500",
        force_live_fetch: bool = False,
        allow_stale: bool = True,
        offline_only: bool = False,
        cache_ttl_days: float = 30.0,
    ) -> ConstituentReconciliationReport:
        """
        Executes complete constituent acquisition, validation, change reconciliation, and freshness evaluation.
        Supports 30-day cache refresh TTL policy:
        - If cache exists and is fresh (age <= 30.0 days) and NOT force_live_fetch, uses cache (CACHED-VALID).
        - If cache is older than 30 days, missing, or force_live_fetch=True, refreshes from live official endpoint (LIVE-VERIFIED).
        - If offline/unreachable, falls back safely to cache if available or fails closed.
        """
        u_key = self._normalize_mode(universe_mode)
        fname = self.FILENAME_MAP.get(u_key, f"ind_{u_key.lower()}list.csv")
        cached_file = self.raw_dir / fname
        if not cached_file.exists():
            alt = self.base_dir / "data" / "raw" / fname
            if alt.exists():
                cached_file = alt
        backup_file = cached_file.with_suffix(".bak")

        prev_symbols, prev_hash = self._load_previous_snapshot(u_key)

        # Handle ALL / ALL_EQUITIES / ALL_STOCKS directly from active SQLite database
        if u_key in ("ALL", "ALL_EQUITIES", "ALL_STOCKS"):
            db_symbols = set()
            try:
                from core.data_engine import get_connection
                with get_connection(read_only=True) as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT symbol FROM prices")
                    db_symbols = {str(row[0]).strip().upper() for row in cursor.fetchall() if row[0]}
            except Exception:
                db_symbols = set()

            if not db_symbols and prev_symbols:
                db_symbols = prev_symbols

            if not db_symbols:
                try:
                    sec_map_file = self.base_dir / "data" / "symbol_sector_map.json"
                    if sec_map_file.exists():
                        with open(sec_map_file, "r", encoding="utf-8") as f:
                            sec_data = json.load(f)
                            db_symbols = {str(s).strip().upper() for s in sec_data.keys()}
                except Exception:
                    pass

            if db_symbols:
                added = sorted(list(db_symbols - prev_symbols)) if prev_symbols else []
                removed = sorted(list(prev_symbols - db_symbols)) if prev_symbols else []
                unchanged = sorted(list(db_symbols.intersection(prev_symbols))) if prev_symbols else sorted(list(db_symbols))
                is_changed = bool(added or removed)

                source_status = ConstituentSourceStatus.LIVE_VERIFIED if not offline_only else ConstituentSourceStatus.CACHED_VALID
                report = ConstituentReconciliationReport(
                    universe_name="ALL",
                    source_status=source_status,
                    source_url="SQLITE_UNIVERSE_DB",
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256="",
                    total_constituents=len(db_symbols),
                    added_symbols=added,
                    removed_symbols=removed,
                    unchanged_symbols=unchanged,
                    is_changed_from_previous=is_changed,
                    warning_message="" if not offline_only else "Universe ALL resolved from local SQLite database (offline mode)",
                )
                self._record_snapshot_idempotent(
                    u_key,
                    {
                        "sha256": "",
                        "snapshot_date": datetime.date.today().isoformat(),
                        "source_url": "SQLITE_UNIVERSE_DB",
                        "status": source_status.value,
                        "total_count": len(db_symbols),
                        "symbols": sorted(list(db_symbols)),
                        "added": added,
                        "removed": removed,
                    },
                )
                return report
            elif allow_stale and prev_symbols:
                return ConstituentReconciliationReport(
                    universe_name="ALL",
                    source_status=ConstituentSourceStatus.CACHED_VALID,
                    source_url="LOCAL_SNAPSHOT_CACHE",
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256=prev_hash,
                    total_constituents=len(prev_symbols),
                    added_symbols=[],
                    removed_symbols=[],
                    unchanged_symbols=sorted(list(prev_symbols)),
                    is_changed_from_previous=False,
                    warning_message="Database symbols unavailable, loaded from snapshot cache",
                )

        urls = self.OFFICIAL_URLS.get(u_key, [])

        cache_exists = cached_file.exists() and cached_file.stat().st_size > 30
        cache_age_days = (time.time() - cached_file.stat().st_mtime) / 86400.0 if cache_exists else 999999.0
        cache_is_fresh = cache_exists and (cache_age_days <= cache_ttl_days)

        use_cached_directly = (not force_live_fetch) and cache_is_fresh

        live_content = None
        source_url_used = "OFFLINE_CACHE"
        fetch_success = False

        if not offline_only and not use_cached_directly:
            live_content, matched_url = self._fetch_live_with_failover(urls, universe_key=u_key)
            if live_content is not None and matched_url:
                source_url_used = matched_url
                fetch_success = True

        if fetch_success and live_content is not None:
            val_res = ConstituentValidator.validate_csv_content(live_content, universe_key=u_key)
            if not val_res.is_valid:
                return ConstituentReconciliationReport(
                    universe_name=u_key,
                    source_status=ConstituentSourceStatus.BLOCKED,
                    source_url=source_url_used,
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256="",
                    total_constituents=0,
                    warning_message=f"Live response failed validation: {val_res.error_message}",
                )

            current_symbols = val_res.valid_symbols
            current_hash = val_res.sha256_hash

            # Strict URL and environment classification
            official_whitelist = self.OFFICIAL_URLS.get(u_key, [])
            is_official = source_url_used in official_whitelist
            is_simulation = any(term in source_url_used.lower() for term in ["mock", "simulat", "test", "synthetic", "fake", "dummy"])

            if is_official and not is_simulation:
                # Genuine official live observation
                source_status = ConstituentSourceStatus.LIVE_VERIFIED
                warning_msg = ""
                # Atomic file publication with backup (only for real official observations)
                try:
                    if cached_file.exists():
                        shutil.copy2(cached_file, backup_file)
                    temp_file = self.raw_dir / f"{fname}.tmp"
                    with open(temp_file, "wb") as f:
                        f.write(live_content)
                    temp_file.replace(cached_file)
                except Exception as e_pub:
                    print(f"Warning during atomic constituent publication: {e_pub}")
            elif is_simulation:
                # Explicit test fixture / mock simulation
                source_status = ConstituentSourceStatus.SIMULATED_TEST_FIXTURE
                warning_msg = f"NOTICE: Executing within simulation fixture ({source_url_used})"
            else:
                # Unauthorized external endpoint -> fail closed!
                return ConstituentReconciliationReport(
                    universe_name=u_key,
                    source_status=ConstituentSourceStatus.BLOCKED,
                    source_url=source_url_used,
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256="",
                    total_constituents=0,
                    warning_message=f"BLOCKED: Endpoint {source_url_used} is not in official NIFTY whitelist.",
                )
        elif cache_exists:
            # Evaluate cached file
            with open(cached_file, "rb") as f:
                cached_bytes = f.read()
            val_res = ConstituentValidator.validate_csv_content(cached_bytes, universe_key=u_key)
            if not val_res.is_valid:
                return ConstituentReconciliationReport(
                    universe_name=u_key,
                    source_status=ConstituentSourceStatus.BLOCKED,
                    source_url="CORRUPTED_CACHE",
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256="",
                    total_constituents=0,
                    warning_message=f"Local cache failed validation: {val_res.error_message}",
                )

            current_symbols = val_res.valid_symbols
            current_hash = val_res.sha256_hash
            file_mtime = cached_file.stat().st_mtime
            age_days = (time.time() - file_mtime) / 86400.0

            if age_days <= cache_ttl_days:
                source_status = ConstituentSourceStatus.CACHED_VALID
                if use_cached_directly:
                    warning_msg = f"Using cached constitution within {cache_ttl_days:.0f}-day refresh window ({age_days:.1f} days old)"
                else:
                    warning_msg = f"Live source unreachable; using valid cached constitution ({age_days:.1f} days old)"
            elif allow_stale:
                source_status = ConstituentSourceStatus.STALE
                warning_msg = f"CRITICAL WARNING: Official source unavailable and cached constitution is STALE ({age_days:.1f} days old)"
            else:
                return ConstituentReconciliationReport(
                    universe_name=u_key,
                    source_status=ConstituentSourceStatus.BLOCKED,
                    source_url="STALE_CACHE_REJECTED",
                    snapshot_date=datetime.date.today().isoformat(),
                    snapshot_sha256=current_hash,
                    total_constituents=len(current_symbols),
                    warning_message=f"Cached constitution exceeds {cache_ttl_days:.0f}-day freshness policy ({age_days:.1f} days old) and allow_stale=False",
                )
        else:
            return ConstituentReconciliationReport(
                universe_name=u_key,
                source_status=ConstituentSourceStatus.BLOCKED,
                source_url="SOURCE_UNAVAILABLE",
                snapshot_date=datetime.date.today().isoformat(),
                snapshot_sha256="",
                total_constituents=0,
                warning_message="Official constituent source unreachable and no valid local cache exists",
            )

        # Baseline change detection
        if prev_symbols:
            added = sorted(list(current_symbols - prev_symbols))
            removed = sorted(list(prev_symbols - current_symbols))
            unchanged = sorted(list(current_symbols.intersection(prev_symbols)))
            is_changed = bool(added or removed or current_hash != prev_hash)
        else:
            added = []
            removed = []
            unchanged = sorted(list(current_symbols))
            is_changed = False

        today_str = datetime.date.today().isoformat()
        report = ConstituentReconciliationReport(
            universe_name=u_key,
            source_status=source_status,
            source_url=source_url_used,
            snapshot_date=today_str,
            snapshot_sha256=current_hash,
            total_constituents=len(current_symbols),
            added_symbols=added,
            removed_symbols=removed,
            unchanged_symbols=unchanged,
            is_changed_from_previous=is_changed,
            warning_message=warning_msg,
        )

        # Persist snapshot idempotently
        self._record_snapshot_idempotent(
            u_key,
            {
                "sha256": current_hash,
                "snapshot_date": today_str,
                "source_url": source_url_used,
                "status": source_status.value,
                "total_count": len(current_symbols),
                "symbols": sorted(list(current_symbols)),
                "added": added,
                "removed": removed,
            },
        )

        return report


class MarketDataReconciliationEngine:
    """
    Reconciles active index constituents against local SQLite market data.
    Provides complete non-silent disposition accounting for every member.
    """

    def __init__(self, base_dir: Optional[Path] = None, target_db_path: Optional[Path] = None):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.prod_db_path = get_db_path()
        self.db_path = Path(target_db_path) if target_db_path else self.prod_db_path
        self.is_production_db = (self.db_path.resolve() == self.prod_db_path.resolve())
        self.sector_map = load_symbol_sector_map()

    def _get_active_db_connection(self) -> sqlite3.Connection:
        if self.is_production_db:
            return get_connection(read_only=True, reuse=True)
        return sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)

    def reconcile_universe_coverage(
        self,
        constituents: Set[str],
        as_of_date: str,
    ) -> MarketDataReconciliationReport:
        """
        Classifies each constituent into PRESENT_CURRENT, PRESENT_STALE, MISSING, or INVALID.
        Guarantees: sum(dispositions) == len(constituents).
        """
        if not constituents:
            return MarketDataReconciliationReport(as_of_date=as_of_date, total_constituents=0)

        conn = self._get_active_db_connection()
        cursor = conn.cursor()

        placeholders = ",".join("?" for _ in constituents)
        query = f"""
            SELECT symbol, MAX(date), COUNT(*),
                   SUM(CASE WHEN date = ? THEN 1 ELSE 0 END)
            FROM prices
            WHERE symbol IN ({placeholders}) AND date <= ?
            GROUP BY symbol;
        """
        params = [as_of_date] + list(constituents) + [as_of_date]
        cursor.execute(query, params)
        db_records = {r[0]: (r[1], r[2], r[3]) for r in cursor.fetchall()}

        # Trading calendar for staleness quantification
        calendar = []
        try:
            calendar = load_trading_calendar()
        except Exception:
            pass

        report = MarketDataReconciliationReport(
            as_of_date=as_of_date,
            total_constituents=len(constituents),
        )

        for sym in constituents:
            rec = db_records.get(sym)
            if not rec or rec[1] == 0:
                report.missing_count += 1
                report.missing_symbols.append(sym)
            else:
                max_d, count_bars, is_today = rec
                if is_today > 0:
                    report.present_current_count += 1
                    report.present_current_symbols.append(sym)
                else:
                    report.present_stale_count += 1
                    # Compute session staleness gap
                    if calendar:
                        gap_sessions = len([d for d in calendar if max_d < d <= as_of_date and d not in KNOWN_NSE_HOLIDAYS])
                    else:
                        gap_sessions = 1
                    report.present_stale_details[sym] = max(1, gap_sessions)

        report.coverage_pct = (report.present_current_count / max(1, len(constituents))) * 100.0
        if not self.is_production_db:
            conn.close()
        return report

def get_canonical_strategy_fingerprint(config: Optional[MIPScannerConfig] = None) -> str:
    """Computes SHA-256 fingerprint from the 9 canonical frozen strategy parameters."""
    cfg = config or MIPScannerConfig()
    params = {
        "ema_regime_span": cfg.ema_regime_span,
        "ema_rs_span": cfg.ema_rs_span,
        "ema_trend_span": cfg.ema_trend_span,
        "exit_buffer_rank": cfg.exit_buffer_rank,
        "max_per_sector": cfg.max_per_sector,
        "momentum_lookback_bars": cfg.momentum_lookback_bars,
        "retrace_threshold": cfg.retrace_threshold,
        "top_n_candidates": cfg.top_n_candidates,
        "volatility_floor": cfg.volatility_floor,
    }
    return hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()


class HardenedScanner(PydroidScanner):
    """
    Hardened Production Scanner for Project MIP.
    Embeds authoritative constituent reconciliation, change detection,
    and end-to-end accounting into the frozen strategy pipeline.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        config: Optional[MIPScannerConfig] = None,
        target_db_path: Optional[Path] = None,
    ):
        super().__init__(base_dir=base_dir, config=config)
        self.prod_db_path = get_db_path()
        self.target_db_path = Path(target_db_path) if target_db_path else self.prod_db_path
        self.is_production_db = (self.target_db_path.resolve() == self.prod_db_path.resolve())
        self.constituent_engine = ConstituentReconciliationEngine(self.base_dir)
        self.data_reconciliation_engine = MarketDataReconciliationEngine(self.base_dir, target_db_path=self.target_db_path)
        self.refresher = HardenedMarketDataRefresher(self.base_dir, target_db_path=self.target_db_path)

    def _record_picks_history(self, target_date: str, top_df: pd.DataFrame, market_bullish: bool):
        """Hardened Scanner enforces zero write mutation on universe.db."""
        return

    def _get_active_latest_date(self) -> str:
        if self.is_production_db:
            return get_latest_date()
        conn = sqlite3.connect(f"file:{self.target_db_path}?mode=ro", uri=True)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM prices;")
        res = cursor.fetchone()
        conn.close()
        return res[0] if (res and res[0]) else get_latest_date()

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
        force_constituent_refresh: bool = False,
        allow_stale_universe: bool = True,
        allow_stale_data: bool = False,
        send_telegram: bool = False,
        auto_download_excel: bool = False,
        use_vol_targeting: bool = False,
        use_delivery_veto: bool = False,
    ) -> Tuple[pd.DataFrame, Dict, Dict, Dict, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """
        Hardened execution of screener pipeline:
          1. Official constituent acquisition, validation & change tracking.
          2. Local market data reconciliation & gap detection.
          3. Standard frozen strategy execution (super().run_scan).
        """
        u_mode = universe_mode or "NIFTY750"
        u_label = get_hardened_universe_label(u_mode)
        self.log(f"Hardened Scanner: Reconciling official constituent universe for [{u_label}]...")
        const_report = self.constituent_engine.fetch_and_reconcile(
            universe_mode=u_mode,
            force_live_fetch=force_constituent_refresh,
            allow_stale=allow_stale_universe,
        )

        if const_report.source_status == ConstituentSourceStatus.BLOCKED:
            raise RuntimeError(f"SCAN ABORTED: Constituent universe resolution BLOCKED. {const_report.warning_message}")

        self.log(
            f"Constituent Status: [{const_report.source_status.value}] | Total: {const_report.total_constituents} | "
            f"Added: {len(const_report.added_symbols)} | Removed: {len(const_report.removed_symbols)} | Unchanged: {len(const_report.unchanged_symbols)}"
        )
        if const_report.warning_message:
            self.log(f"Constituent Warning: {const_report.warning_message}")

        target_date = as_of_date if as_of_date else self._get_active_latest_date()
        u_norm_key = self.constituent_engine._normalize_mode(u_mode)
        cached_file = self.constituent_engine.raw_dir / self.constituent_engine.FILENAME_MAP.get(u_norm_key, "")
        constituents_set = set()
        if cached_file.exists():
            try:
                df_c = pd.read_csv(cached_file)
                sym_col = [c for c in df_c.columns if str(c).strip().upper() == "SYMBOL"][0]
                constituents_set = set(df_c[sym_col].astype(str).str.strip().str.upper())
            except Exception:
                pass
        if not constituents_set and const_report.valid_symbols:
            constituents_set = set(const_report.valid_symbols)

        data_reconcile_report = self.data_reconciliation_engine.reconcile_universe_coverage(
            constituents=constituents_set,
            as_of_date=target_date,
        )
        self.log(
            f"Data Reconciliation as of {target_date}: {data_reconcile_report.present_current_count} Current | "
            f"{data_reconcile_report.present_stale_count} Stale | {data_reconcile_report.missing_count} Missing | "
            f"Coverage: {data_reconcile_report.coverage_pct:.2f}%"
        )

        if not self.is_production_db:
            from unittest.mock import patch
            import core.scanner as cs

            def _hardened_load_universe(m=None, force_refresh=False):
                return constituents_set

            def _hardened_get_u_label(m=None):
                return get_hardened_universe_label(u_mode)
            def _sandbox_load_bars(start_date=None, end_date=None, symbols=None, include_delisted=True):
                sb_c = sqlite3.connect(f"file:{self.target_db_path}?mode=ro", uri=True)
                conds, params = [], []
                if start_date:
                    conds.append("date >= ?"); params.append(str(start_date))
                if end_date:
                    conds.append("date <= ?"); params.append(str(end_date))
                if symbols:
                    pl = ",".join("?" for _ in symbols)
                    conds.append(f"symbol IN ({pl})"); params.extend(symbols)
                if not include_delisted:
                    conds.append("is_delisted = 0")
                w = f"WHERE {' AND '.join(conds)}" if conds else ""
                q = f"SELECT date, symbol, open, high, low, close, volume, is_delisted FROM prices {w} ORDER BY date ASC, symbol ASC;"
                df_sb = pd.read_sql_query(q, sb_c, params=params)
                sb_c.close()
                if not df_sb.empty:
                    df_sb["is_delisted"] = df_sb["is_delisted"].astype(bool)
                return df_sb

            with patch.object(cs, "load_bars", side_effect=_sandbox_load_bars), \
                 patch.object(cs, "load_universe_constituents", side_effect=_hardened_load_universe), \
                 patch.object(cs, "get_universe_label", side_effect=_hardened_get_u_label):
                res = super().run_scan(
                    as_of_date=as_of_date,
                    universe_mode=universe_mode,
                    top_n=top_n,
                    lookback_days=lookback_days,
                    max_per_sector=max_per_sector,
                    export_csv=export_csv,
                    export_excel=export_excel,
                    auto_update_universe=auto_update_universe,
                    allow_stale_data=allow_stale_data,
                    send_telegram=send_telegram,
                    auto_download_excel=False,
                )
        else:
            res = super().run_scan(
                as_of_date=as_of_date,
                universe_mode=universe_mode,
                top_n=top_n,
                lookback_days=lookback_days,
                max_per_sector=max_per_sector,
                export_csv=export_csv,
                export_excel=export_excel,
                auto_update_universe=auto_update_universe,
                allow_stale_data=allow_stale_data,
                send_telegram=send_telegram,
                auto_download_excel=False,
            )

        top_df = res[0]
        if use_delivery_veto and top_df is not None and not top_df.empty:
            if "delivery_action" in top_df.columns:
                vetoed_mask = top_df["delivery_action"].astype(str).str.contains("DISTRIBUTION|VETO", na=False)
                vetoed_syms = top_df.loc[vetoed_mask, "symbol"].tolist()
                if vetoed_syms:
                    self.log(f"🛡️ Delivery Microstructure Veto: Excluded {len(vetoed_syms)} distribution candidate(s): {', '.join(vetoed_syms)}")
                    top_df["is_delivery_vetoed"] = top_df["symbol"].isin(vetoed_syms)
                    top_df.loc[top_df["is_delivery_vetoed"], "allow_buy"] = False
                    top_df.loc[top_df["is_delivery_vetoed"], "target_qty"] = 0
                    top_df.loc[top_df["is_delivery_vetoed"], "target_val"] = 0.0
                    top_df.attrs["delivery_vetoed_symbols"] = vetoed_syms

        if use_vol_targeting and top_df is not None and not top_df.empty:
            try:
                from nextgen.volatility_targeting import compute_ewma_realized_volatility, compute_dynamic_cash_shield_scalar
                b_df = self.load_benchmark()
                if not b_df.empty and "close" in b_df.columns:
                    b_rets = b_df["close"].pct_change().dropna()
                    ewma_vol = compute_ewma_realized_volatility(b_rets)
                    current_vol = float(ewma_vol.iloc[-1]) if not ewma_vol.empty else 0.15
                    breadth_res = res[1] if len(res) > 1 else {}
                    b_tp = breadth_res.get("trend_participation", {}) if isinstance(breadth_res, dict) else {}
                    b_ratio = float(b_tp.get("pct_above_200_ema", 50.0)) / 100.0
                    regime_res = res[3] if len(res) > 3 else {}
                    is_bull = bool(regime_res.get("is_normal_regime", True)) if isinstance(regime_res, dict) else True
                    shield_scalar = compute_dynamic_cash_shield_scalar(
                        is_bull_regime=is_bull,
                        realized_vol=current_vol,
                        target_vol=0.12,
                        breadth_ratio=b_ratio,
                    )
                    top_df["target_qty"] = (top_df["target_qty"] * shield_scalar).astype(int)
                    top_df["target_val"] = (top_df["target_qty"] * top_df["close"]).round(2)
                    top_df.attrs["shield_scalar"] = shield_scalar
                    top_df.attrs["market_realized_vol"] = current_vol
                    self.log(f"🛡️ Dynamic Cash Shield: Exposure scaled to {shield_scalar*100:.1f}% Equity / {(1-shield_scalar)*100:.1f}% Cash (Realized Vol: {current_vol*100:.2f}%)")
            except Exception as e_shield:
                self.log(f"Dynamic cash shield notice: {e_shield}")

        if auto_download_excel and hasattr(top_df, "attrs"):
            excel_path = top_df.attrs.get("excel_path")
            if excel_path and Path(excel_path).exists():
                dl_ok = trigger_colab_download(excel_path, cooldown_seconds=20.0)
                top_df.attrs["excel_downloaded"] = dl_ok
        disposition_summary = {
            "total_constituents": const_report.total_constituents,
            "present_current": data_reconcile_report.present_current_count,
            "present_stale": data_reconcile_report.present_stale_count,
            "missing": data_reconcile_report.missing_count,
            "invalid": data_reconcile_report.invalid_count,
            "coverage_pct": data_reconcile_report.coverage_pct,
            "strategy_fingerprint": get_canonical_strategy_fingerprint(self.config),
            "constituent_source_status": const_report.source_status.value,
            "snapshot_sha256": const_report.snapshot_sha256,
            "top_candidates_selected": len(top_df) if top_df is not None else 0,
        }

        if hasattr(top_df, "attrs"):
            top_df.attrs["constituent_report"] = const_report
            top_df.attrs["data_reconcile_report"] = data_reconcile_report
            top_df.attrs["disposition_summary"] = disposition_summary
            top_df.attrs["breadth_results"] = res[1] if len(res) > 1 else None
            top_df.attrs["sector_results"] = res[2] if len(res) > 2 else None

        return res

    def run_hardened_scan(
        self,
        as_of_date: Optional[str] = None,
        universe_mode: str = "NIFTY500",
        force_constituent_refresh: bool = False,
        allow_stale_universe: bool = True,
        auto_update_universe: bool = False,
        export_reports: bool = True,
    ) -> Tuple[pd.DataFrame, Dict[str, Any], ConstituentReconciliationReport, MarketDataReconciliationReport]:
        """
        Executes end-to-end hardened scanning workflow returning explicit disposition tuple:
          (top_df, disposition_summary, const_report, data_reconcile_report)
        """
        res = self.run_scan(
            as_of_date=as_of_date,
            universe_mode=universe_mode,
            auto_update_universe=auto_update_universe,
            export_csv=export_reports,
            export_excel=export_reports,
            force_constituent_refresh=force_constituent_refresh,
            allow_stale_universe=allow_stale_universe,
        )
        top_df = res[0]
        const_report = top_df.attrs.get("constituent_report")
        data_reconcile_report = top_df.attrs.get("data_reconcile_report")
        disposition_summary = top_df.attrs.get("disposition_summary", {})
        return top_df, disposition_summary, const_report, data_reconcile_report


class HardenedMarketDataRefresher(PydroidAutoFetch):
    """
    Hardened Market Data Refresh Engine for Project MIP.
    Safely coordinates missing/stale session discovery, bhavcopy acquisition,
    geometric OHLCV validation, and persistence with strict production immutability safeguards.
    """

    def __init__(self, base_dir: Optional[Path] = None, target_db_path: Optional[Path] = None):
        super().__init__(base_dir=base_dir)
        self.prod_db_path = get_db_path()
        self.target_db_path = Path(target_db_path) if target_db_path else self.prod_db_path
        self.is_production_db = (self.target_db_path.resolve() == self.prod_db_path.resolve())
        self.last_acquisition_source = "NONE"
        self.last_records_validated = 0
        self.last_records_rejected = 0

    def _get_active_db_connection(self, read_only: bool = True) -> sqlite3.Connection:
        if self.is_production_db:
            if not read_only and os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1":
                raise PermissionError("PRODUCTION IMMUTABILITY VIOLATION: Direct write mutation to production universe.db is strictly prohibited.")
            return get_connection(read_only=read_only, reuse=False)
        else:
            if read_only:
                return sqlite3.connect(f"file:{self.target_db_path}?mode=ro", uri=True)
            return sqlite3.connect(str(self.target_db_path))

    def get_missing_trading_dates(self, as_of_date: Optional[str] = None) -> List[str]:
        target = as_of_date if as_of_date else datetime.datetime.now().strftime("%Y-%m-%d")
        conn = self._get_active_db_connection(read_only=True)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM prices;")
        res = cursor.fetchone()
        max_date = res[0] if res and res[0] else None
        conn.close()

        if not max_date:
            return []

        missing = []
        try:
            calendar = load_trading_calendar()
        except Exception:
            calendar = []

        for d in calendar:
            if max_date < d <= target and d not in KNOWN_NSE_HOLIDAYS:
                missing.append(d)
        return sorted(list(set(missing)))

    def _validate_ohlcv_geometries(self, df: pd.DataFrame, date_str: str) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return None
        valid_mask = (
            (df["high"] >= df["low"]) &
            (df["high"] >= df["open"]) &
            (df["high"] >= df["close"]) &
            (df["low"] <= df["open"]) &
            (df["low"] <= df["close"]) &
            (df["open"] > 0) &
            (df["close"] > 0) &
            (df["volume"] >= 0)
        )
        rejected = int((~valid_mask).sum())
        self.last_records_rejected += rejected
        if rejected > 0:
            self.log(f"Rejected {rejected} bars on {date_str} violating OHLCV geometric invariants.")
            df = df[valid_mask].copy()
            if df.empty:
                return None
        self.last_records_validated += len(df)
        return df

    def fetch_bhavcopy_for_date(self, date_str: str, force_live: bool = False) -> Optional[pd.DataFrame]:
        # 1. Probe local delivery cache first (unless force_live is True)
        if not force_live:
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            local_cache = self.base_dir / "data" / "bhavcopy_delivery" / f"sec_bhavdata_{dt.strftime('%Y%m%d')}.csv"
            if local_cache.exists():
                try:
                    raw = pd.read_csv(local_cache)
                    df = self._standardize_bhavcopy(raw, date_str)
                    if df is not None and not df.empty:
                        df = df[df["date"] == date_str]
                        df = self._validate_ohlcv_geometries(df, date_str)
                        if df is not None and not df.empty:
                            self.last_acquisition_source = "LOCAL_DELIVERY_CACHE"
                            return df
                except Exception as e:
                    self.log(f"Warning reading local bhavcopy cache {local_cache.name}: {e}")

        # 2. Upstream live acquisition
        df = super().fetch_bhavcopy_for_date(date_str)
        if df is not None and not df.empty:
            # Trade-date validation: prevent holiday/redirected prior session contamination
            df = df[df["date"] == date_str]
            df = self._validate_ohlcv_geometries(df, date_str)
            if df is not None and not df.empty:
                self.last_acquisition_source = "LIVE_NSE_ARCHIVES"
                return df
            else:
                self.log(f"Rejected upstream bhavcopy for {date_str}: Trade date mismatch or invalid geometries.")
        return None

    def refresh_missing_sessions(self, target_date: Optional[str] = None, dry_run: bool = False, force_live: bool = False) -> Dict[str, Any]:
        """
        Executes complete missing/stale session discovery, validation, and ingestion.
        Guarantees that production database is never written unless explicitly authorized.
        """
        missing = self.get_missing_trading_dates(target_date)
        if not missing:
            return {
                "status": AutoFetchStatus.CURRENT.value,
                "dates_fetched": 0,
                "missing_dates": [],
                "target_db": str(self.target_db_path),
                "is_production": self.is_production_db,
                "acquisition_source": "NONE",
                "message": "Target database is already current.",
            }

        valid_symbols = self.get_expanded_universe_symbols()
        new_frames = []
        sources_used = []
        for d in missing:
            df = self.fetch_bhavcopy_for_date(d, force_live=force_live)
            if df is not None and not df.empty:
                if valid_symbols:
                    df = df[df["symbol"].isin(valid_symbols)]
                df["is_delisted"] = 0
                new_frames.append(df)
                sources_used.append(self.last_acquisition_source)

        if dry_run or (self.is_production_db and os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1"):
            return {
                "status": "SAFETY_CONTROL_DRY_RUN",
                "dates_fetched": len(new_frames),
                "missing_dates": missing,
                "target_db": str(self.target_db_path),
                "is_production": self.is_production_db,
                "rows_validated": sum(len(f) for f in new_frames),
                "acquisition_source": ",".join(set(sources_used)) if sources_used else "NONE",
                "safety_control": "Production Immutability Firewall (Writes blocked without MIP_ALLOW_PROD_MUTATION=1)",
            }

        # Safe sandbox persistence with transactional atomic commit & rollback
        conn = self._get_active_db_connection(read_only=False)
        upsert = """
            INSERT OR REPLACE INTO prices 
            (date, symbol, open, high, low, close, volume, is_delisted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """
        total_rows = 0
        try:
            for df in new_frames:
                rows = [
                    (str(r["date"]), str(r["symbol"]), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]), float(r["volume"]), 0)
                    for _, r in df.iterrows()
                ]
                conn.executemany(upsert, rows)
                total_rows += len(rows)
            conn.commit()
        except Exception as e_tx:
            conn.rollback()
            conn.close()
            self.log(f"Transaction failed during refresh: {e_tx}. Rolled back.")
            raise

        # Update trading calendar and sector map
        self._update_trading_calendar(missing)
        all_syms = set()
        for df in new_frames:
            all_syms.update(df["symbol"].unique())
        self._update_symbol_sector_map(all_syms)

        conn.close()
        return {
            "status": AutoFetchStatus.UPDATED.value,
            "dates_fetched": len(new_frames),
            "missing_dates": missing,
            "rows_inserted": total_rows,
            "target_db": str(self.target_db_path),
            "is_production": self.is_production_db,
            "acquisition_source": ",".join(set(sources_used)) if sources_used else "NONE",
        }


