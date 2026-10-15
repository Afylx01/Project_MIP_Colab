import os
import sys
import io
import csv
import json
import shutil
import zipfile
import sqlite3
import datetime
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Set
import pandas as pd
import numpy as np

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    cffi_requests = None
    import requests

from enum import Enum
from . import data_engine as _de
from .benchmark_validator import BenchmarkSyncResult


class AutoFetchStatus(str, Enum):
    CURRENT = "CURRENT"
    UPDATED = "UPDATED"
    NO_NEW_SESSION = "NO_NEW_SESSION"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    DATA_INVALID = "DATA_INVALID"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"


class PydroidAutoFetch:
    def __init__(self, base_dir: Path = None):
        self.base_dir = Path(base_dir) if base_dir else _de.get_base_dir()
        self.session = None

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] PydroidAutoFetch: {msg}")

    def _get_session(self):
        if self.session is None:
            if cffi_requests:
                self.session = cffi_requests.Session(impersonate="chrome")
            else:
                self.session = requests.Session()
                self.session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                })
        return self.session

    def get_missing_trading_dates(self, as_of_date: str = None) -> List[str]:
        target = as_of_date if as_of_date else _de.get_expected_latest_eod()
        conn = _de.get_connection(read_only=True, reuse=True)
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM prices;")
        res = cursor.fetchone()
        max_date = res[0] if res and res[0] else None

        if not max_date:
            self.log("No data in DB. Fetching last 30 days as fallback.")
            max_date = (datetime.datetime.strptime(target, "%Y-%m-%d") - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

        missing = []
        try:
            calendar = _de.load_trading_calendar()
        except Exception as e:
            self.log(f"Error loading calendar: {e}. Falling back to weekdays.")
            calendar = []

        # 1. Any calendar dates strictly between max_date and target (excluding known holidays)
        for d in calendar:
            if max_date < d <= target and d not in _de.KNOWN_NSE_HOLIDAYS:
                missing.append(d)

        # 2. If target extends beyond calendar[-1] (or calendar is empty)
        cal_end = calendar[-1] if calendar else max_date
        if target > cal_end:
            start_d = max(
                datetime.datetime.strptime(max_date, "%Y-%m-%d").date(),
                datetime.datetime.strptime(cal_end, "%Y-%m-%d").date()
            ) + datetime.timedelta(days=1)
            end_d = datetime.datetime.strptime(target, "%Y-%m-%d").date()
            curr = start_d
            while curr <= end_d:
                d_str = curr.strftime("%Y-%m-%d")
                if curr.weekday() < 5 and d_str not in _de.KNOWN_NSE_HOLIDAYS and d_str not in missing:
                    missing.append(d_str)
                curr += datetime.timedelta(days=1)

        return sorted(list(set(missing)))

    def fetch_bhavcopy_for_date(self, date_str: str) -> Optional[pd.DataFrame]:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        session = self._get_session()
        
        urls = [
            f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{dt.strftime('%Y%m%d')}_F_0000.csv.zip",
            f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{dt.strftime('%d%m%Y')}.csv",
            f"https://archives.nseindia.com/content/historical/EQUITIES/{dt.strftime('%Y')}/{dt.strftime('%b').upper()}/cm{dt.strftime('%d%b%Y').upper()}bhav.csv.zip",
        ]
        
        for url in urls:
            self.log(f"Fetching {url}")
            try:
                resp = session.get(url, timeout=12)
                if resp.status_code == 200 and resp.content:
                    if url.endswith(".zip") or resp.content[:2] == b"PK":
                        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                            csv_names = [n for n in z.namelist() if n.endswith('.csv')]
                            if not csv_names:
                                self.log(f"No CSV file found inside archive from {url}")
                                continue
                            csv_name = csv_names[0]
                            # Decompression bomb safeguard: Max 50MB uncompressed (CWE-409)
                            info = z.getinfo(csv_name)
                            if info.file_size > 50 * 1024 * 1024:
                                self.log(f"Security Alert: Uncompressed size exceeds 50MB limit ({info.file_size} bytes)")
                                continue
                            with z.open(csv_name) as f:
                                raw = pd.read_csv(f)
                                return self._standardize_bhavcopy(raw, date_str)
                    else:
                        raw = pd.read_csv(io.BytesIO(resp.content))
                        return self._standardize_bhavcopy(raw, date_str)
                else:
                    self.log(f"Status {resp.status_code} for {url}")
            except Exception as e:
                self.log(f"Error fetching {url}: {e}")
        return None

    def _standardize_bhavcopy(self, raw: pd.DataFrame, fallback_date: str) -> pd.DataFrame:
        raw.columns = [c.strip().upper() for c in raw.columns]
        
        if 'TCKRSYMB' in raw.columns:
            sym_col, series_col = 'TCKRSYMB', 'SCTYSRS'
            opn_col, hgh_col, low_col, cls_col, vol_col = 'OPNPRIC', 'HGHPRIC', 'LWPRIC', 'CLSPRIC', 'TTLTRADGVOL'
            dt_col = 'TRADDT'
        elif 'OPEN_PRICE' in raw.columns and 'SYMBOL' in raw.columns:
            sym_col, series_col = 'SYMBOL', 'SERIES'
            opn_col, hgh_col, low_col, cls_col, vol_col = 'OPEN_PRICE', 'HIGH_PRICE', 'LOW_PRICE', 'CLOSE_PRICE', 'TTL_TRD_QNTY'
            dt_col = 'DATE1'
        elif 'SYMBOL' in raw.columns:
            sym_col, series_col = 'SYMBOL', 'SERIES'
            opn_col, hgh_col, low_col, cls_col, vol_col = 'OPEN', 'HIGH', 'LOW', 'CLOSE', 'TOTTRDQTY'
            dt_col = 'TIMESTAMP'
        else:
            self.log(f"Unknown bhavcopy format. Columns: {raw.columns}")
            return pd.DataFrame()
            
        raw = raw[raw[series_col].astype(str).str.strip().isin(['EQ', 'BE', 'BZ'])].copy()
        
        if dt_col in raw.columns:
            try:
                raw['date'] = pd.to_datetime(raw[dt_col]).dt.strftime("%Y-%m-%d")
            except:
                raw['date'] = fallback_date
        else:
            raw['date'] = fallback_date
            
        res = pd.DataFrame({
            'date': raw['date'],
            'symbol': raw[sym_col].astype(str).str.strip(),
            'open': pd.to_numeric(raw[opn_col], errors='coerce'),
            'high': pd.to_numeric(raw[hgh_col], errors='coerce'),
            'low': pd.to_numeric(raw[low_col], errors='coerce'),
            'close': pd.to_numeric(raw[cls_col], errors='coerce'),
            'volume': pd.to_numeric(raw[vol_col], errors='coerce')
        })
        
        res = res.dropna()
        res = res[(res['open'] > 0) & (res['high'] > 0) & (res['low'] > 0) & (res['close'] > 0)]
        return res

    def fetch_corporate_actions(self, start_date: str, end_date: str) -> List[Dict]:
        session = self._get_session()
        try:
            self.log("Visiting nseindia.com for cookies")
            session.get("https://www.nseindia.com", timeout=10)
            
            url = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
            self.log(f"Fetching corporate actions from {url}")
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return data if isinstance(data, list) else []
            else:
                self.log(f"Failed to fetch corporate actions, status: {resp.status_code}")
                return []
        except Exception as e:
            self.log(f"Error fetching corporate actions: {e}")
            return []

    def parse_corporate_actions(self, raw_actions: List[Dict], start_date: str, end_date: str) -> List[Dict]:
        parsed = []
        for action in raw_actions:
            ex_date_str = action.get('exDate', '')
            if not ex_date_str or ex_date_str == '-':
                continue
            
            try:
                ex_date = datetime.datetime.strptime(ex_date_str, "%d-%b-%Y").strftime("%Y-%m-%d")
            except:
                continue
                
            if not (start_date <= ex_date <= end_date):
                continue
                
            symbol = str(action.get('symbol', '')).strip().upper()
            subject = str(action.get('subject', '')).lower()
            
            # Robust regex for splits/sub-divisions: capture old and new face values
            m_split = re.search(r'(?:split|sub-division).*?rs\.?\s*(\d+(?:\.\d+)?).*?to.*?rs\.?\s*(\d+(?:\.\d+)?)', subject)
            if m_split:
                try:
                    old_fv = float(m_split.group(1))
                    new_fv = float(m_split.group(2))
                    if old_fv > 0 and new_fv > 0:
                        parsed.append({'symbol': symbol, 'ex_date': ex_date, 'type': 'split', 'factor': new_fv / old_fv})
                except (ValueError, TypeError, IndexError):
                    pass
                continue
                
            m_bonus = re.search(r'bonus.*?(\d+)\s*:\s*(\d+)', subject)
            if m_bonus:
                try:
                    new_shares = float(m_bonus.group(1))
                    old_shares = float(m_bonus.group(2))
                    if old_shares > 0:
                        parsed.append({'symbol': symbol, 'ex_date': ex_date, 'type': 'bonus', 'factor': old_shares / (old_shares + new_shares)})
                except (ValueError, TypeError, IndexError):
                    pass
                continue
                
            m_div = re.search(r'dividend.*?(?:rs|inr)\.?\s*(\d+(?:\.\d+)?)', subject)
            if m_div:
                try:
                    div_amt = float(m_div.group(1))
                    parsed.append({'symbol': symbol, 'ex_date': ex_date, 'type': 'dividend', 'amount': div_amt})
                except (ValueError, TypeError, IndexError):
                    pass
                continue

            # Phase 4.1 Structural Reorganizations & Non-Split Events
            from .anomaly import classify_corporate_action, CorporateActionType
            reorg_type = classify_corporate_action(subject)
            if reorg_type != CorporateActionType.UNKNOWN_MATERIAL_EVENT:
                parsed.append({
                    'symbol': symbol,
                    'ex_date': ex_date,
                    'type': reorg_type.value.lower(),
                    'factor': None,
                    'amount': None,
                })
        return parsed

    def apply_backward_adjustments(self, conn: sqlite3.Connection, parsed_actions: List[Dict]):
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS applied_corporate_actions (
                symbol TEXT NOT NULL,
                ex_date TEXT NOT NULL,
                type TEXT NOT NULL,
                factor REAL,
                amount REAL,
                applied_at TEXT NOT NULL,
                PRIMARY KEY (symbol, ex_date, type)
            );
        """)

        cursor.execute("SELECT MAX(date) FROM prices")
        max_date_row = cursor.fetchone()
        max_bhav_date = max_date_row[0] if (max_date_row and max_date_row[0]) else None

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for act in parsed_actions:
            sym = act['symbol']
            ex_date = act['ex_date']
            act_type = act['type']

            # Temporal guard: never apply corporate action before ex_date has occurred in prices
            if not max_bhav_date or ex_date > max_bhav_date:
                self.log(f"Skipping future corporate action: {act_type} for {sym} on ex_date {ex_date} > latest data date {max_bhav_date}")
                continue

            # Check idempotency ledger: do not re-apply action if already processed
            cursor.execute(
                "SELECT 1 FROM applied_corporate_actions WHERE symbol=? AND ex_date=? AND type=?",
                (sym, ex_date, act_type)
            )
            if cursor.fetchone():
                self.log(f"Skipping already applied corporate action: {act_type} for {sym} on {ex_date}")
                continue

            if act_type in ['split', 'bonus']:
                factor = act['factor']
                vol_factor = 1.0 / factor
                self.log(f"Recording {act_type} for {sym} before {ex_date}, factor {factor:.6f} (dynamic in-memory adjustment via AnalyticalPriceEngine)")
                cursor.execute(
                    "INSERT OR REPLACE INTO applied_corporate_actions (symbol, ex_date, type, factor, amount, applied_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sym, ex_date, act_type, factor, None, now_str)
                )
            elif act_type == 'dividend':
                # Cash dividends do NOT mutate historical OHLCV bars under price-return momentum methodology.
                self.log(f"Recording dividend for {sym} on {ex_date} (amt: {act['amount']}) - price adjustment omitted under price-return methodology")
                cursor.execute(
                    "INSERT OR REPLACE INTO applied_corporate_actions (symbol, ex_date, type, factor, amount, applied_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sym, ex_date, act_type, 1.0, act['amount'], now_str)
                )
            else:
                # Structural Reorganizations (DEMERGER, SPIN_OFF, CAPITAL_REDUCTION, SCHEME_OF_ARRANGEMENT, etc.)
                # Fail-closed: Record in ledger without speculative factor adjustment.
                self.log(f"Recording unresolved structural reorganization: {act_type} for {sym} on {ex_date} (no speculative factor applied)")
                cursor.execute(
                    "INSERT OR REPLACE INTO applied_corporate_actions (symbol, ex_date, type, factor, amount, applied_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sym, ex_date, act_type, None, None, now_str)
                )

    def validate_database(self, conn: sqlite3.Connection) -> Tuple[bool, str]:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prices WHERE open IS NULL OR high IS NULL OR low IS NULL OR close IS NULL")
        null_count = cursor.fetchone()[0]
        if null_count > 0:
            return False, f"Found {null_count} rows with null prices"
            
        cursor.execute("SELECT COUNT(*) FROM prices WHERE open <= 0 OR high <= 0 OR low <= 0 OR close <= 0")
        neg_count = cursor.fetchone()[0]
        if neg_count > 0:
            return False, f"Found {neg_count} rows with non-positive prices"
            
        cursor.execute("SELECT symbol, date, COUNT(*) FROM prices GROUP BY symbol, date HAVING COUNT(*) > 1")
        dupes = cursor.fetchone()
        if dupes:
            return False, f"Found duplicates, e.g., symbol {dupes[0]} on {dupes[1]}"
            
        return True, "Database valid"

    def get_expanded_universe_symbols(self) -> Set[str]:
        """
        Dynamically merges valid symbols across:
          1. Existing symbols in SQLite prices table.
          2. Active symbols in data/symbol_sector_map.json.
          3. Official constituents from ind_nifty500list.csv.
          4. Official constituents from ind_niftytotalmarket_list.csv.
        Ensures newly listed or index-included stocks are never filtered out.
        """
        symbols = set()
        try:
            conn = _de.get_connection(read_only=True, reuse=True)
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT symbol FROM prices")
            symbols.update(row[0] for row in cursor.fetchall())
        except Exception as e:
            self.log(f"Warning reading DB symbols: {e}")

        # Add symbols from symbol_sector_map.json
        sec_map_path = self.base_dir / "data" / "symbol_sector_map.json"
        if sec_map_path.exists():
            try:
                with open(sec_map_path, "r", encoding="utf-8") as f:
                    s_map = json.load(f)
                    symbols.update(s_map.keys())
            except Exception as e:
                self.log(f"Warning reading sector map: {e}")

        # Add symbols from raw_reference index lists
        raw_dir = self.base_dir / "data" / "raw_reference"
        for fname in ["ind_nifty500list.csv", "ind_niftytotalmarket_list.csv"]:
            fpath = raw_dir / fname
            if fpath.exists():
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        reader = csv.DictReader(f)
                        for r in reader:
                            s = r.get("Symbol", "").strip()
                            if s:
                                symbols.add(s)
                except Exception as e:
                    self.log(f"Warning reading {fname}: {e}")

        self.log(f"Dynamic universe constituent registry: {len(symbols):,} allowed symbols")
        return symbols

    def _update_trading_calendar(self, new_dates: List[str]):
        """Persists newly fetched trading sessions into data/trading_calendar.txt."""
        cal_path = self.base_dir / "data" / "trading_calendar.txt"
        if not cal_path.exists():
            return
        try:
            with open(cal_path, "r", encoding="utf-8") as f:
                existing_dates = set(line.strip() for line in f if line.strip())
            
            added = [d for d in new_dates if d not in existing_dates]
            if added:
                all_dates = sorted(existing_dates.union(added))
                with open(cal_path, "w", encoding="utf-8") as f:
                    for d in all_dates:
                        f.write(f"{d}\n")
                self.log(f"✓ Updated trading calendar with {len(added)} new sessions up to {all_dates[-1]}")
        except Exception as e:
            self.log(f"Warning updating trading calendar: {e}")

    def _update_symbol_sector_map(self, symbols: Set[str]):
        """Ensures newly added symbols are assigned sectors in symbol_sector_map.json."""
        sec_map_path = self.base_dir / "data" / "symbol_sector_map.json"
        if not sec_map_path.exists():
            return
        try:
            with open(sec_map_path, "r", encoding="utf-8") as f:
                s_map = json.load(f)
            
            missing = [s for s in symbols if s not in s_map]
            if missing:
                from .sync_sectors import classify_symbol, EXPLICIT_OVERRIDES
                for s in missing:
                    s_map[s] = EXPLICIT_OVERRIDES.get(s, classify_symbol(s))
                with open(sec_map_path, "w", encoding="utf-8") as f:
                    json.dump(s_map, f, indent=2, sort_keys=True)
                self.log(f"✓ Classified and registered {len(missing)} newly discovered symbols into sector map.")
        except Exception as e:
            self.log(f"Warning updating sector map for new symbols: {e}")

    def sync_universe(self, target_date: str = None, dry_run: bool = False) -> Dict:
        self.log(f"Starting sync_universe, target_date={target_date}, dry_run={dry_run}")
        
        sync_res = {"status": "SKIPPED", "message": "No new data"}
        missing_dates = self.get_missing_trading_dates(target_date)
        if not missing_dates:
            self.log("No missing dates to fetch.")
            conn = _de.get_connection(read_only=True, reuse=True)
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(date) FROM prices;")
            res = cursor.fetchone()
            db_latest = res[0] if res and res[0] else None
            return {
                "status": AutoFetchStatus.CURRENT.value,
                "dates_fetched": 0,
                "actions_applied": 0,
                "db_latest": db_latest,
                "message": "Database is already current up to target date."
            }
            
        self.log(f"Missing dates to fetch: {missing_dates}")
        
        valid_symbols = self.get_expanded_universe_symbols()
        
        new_data_frames = []
        for d in missing_dates:
            df = self.fetch_bhavcopy_for_date(d)
            if df is not None and not df.empty:
                if valid_symbols:
                    df = df[df['symbol'].isin(valid_symbols)]
                df['is_delisted'] = 0
                new_data_frames.append(df)
                self.log(f"Fetched {len(df)} records for {d}")
            else:
                self.log(f"No data for {d}")

        if not new_data_frames:
            self.log(f"No bhavcopy data could be acquired for missing dates: {missing_dates}")
            return {
                "status": AutoFetchStatus.SOURCE_UNAVAILABLE.value,
                "dates_fetched": 0,
                "actions_applied": 0,
                "missing_dates": missing_dates,
                "message": f"Source Bhavcopy archives unavailable for {missing_dates}"
            }
                
        actions_applied = 0
        if dry_run:
            return {
                "status": AutoFetchStatus.CURRENT.value,
                "dates_fetched": len(new_data_frames),
                "actions_applied": 0,
                "dry_run": True,
                "message": "Dry run completed successfully."
            }

        # PRODUCTION IMMUTABILITY FIREWALL:
        # Check production immutability firewall before attempting any write or backup
        if os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1":
            self.log("SAFETY CONTROL FIREWALL: Production database writes blocked (MIP_ALLOW_PROD_MUTATION != 1). Returning safety dry-run status.")
            return {
                "status": "SAFETY_CONTROL_DRY_RUN",
                "dates_fetched": 0,
                "actions_applied": 0,
                "message": "Production writes blocked by firewall (MIP_ALLOW_PROD_MUTATION != 1)."
            }

        # Pre-update database backup
        db_path = _de.get_db_path()
        try:
            bak_path = db_path.with_suffix(".db.bak")
            with sqlite3.connect(db_path) as src_conn, sqlite3.connect(bak_path) as dst_conn:
                src_conn.backup(dst_conn)
            self.log(f"Created pre-update database backup via SQLite backup API: {bak_path.name}")
        except Exception as e_bak:
            self.log(f"Warning: Could not create pre-update backup: {e_bak}")

        write_conn = _de.get_connection(read_only=False, reuse=False)
        try:
            upsert_query = """
                INSERT OR REPLACE INTO prices 
                (date, symbol, open, high, low, close, volume, is_delisted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """
            for df in new_data_frames:
                rows_to_insert = [
                    (
                        str(row['date']),
                        str(row['symbol']),
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        float(row['volume']),
                        int(row.get('is_delisted', 0))
                    )
                    for _, row in df.iterrows()
                ]
                write_conn.executemany(upsert_query, rows_to_insert)
            
            start_ca, end_ca = missing_dates[0], missing_dates[-1]
            raw_ca = self.fetch_corporate_actions(start_ca, end_ca)
            parsed_ca = self.parse_corporate_actions(raw_ca, start_ca, end_ca)
            if parsed_ca:
                self.apply_backward_adjustments(write_conn, parsed_ca)
                actions_applied = len(parsed_ca)
            
            is_valid, msg = self.validate_database(write_conn)
            if not is_valid:
                write_conn.rollback()
                self.log(f"Database validation failed: {msg}. Rolled back transaction.")
                return {"status": AutoFetchStatus.DATA_INVALID.value, "message": f"Validation failed: {msg}"}

            write_conn.commit()
            self.log(f"Successfully committed {sum(len(df) for df in new_data_frames):,} bars and {actions_applied} corporate actions.")
            _de._CACHED_CONN = None
            
            # 1. Update calendar
            self._update_trading_calendar(missing_dates)

            # 2. Update sector map for new symbols
            all_new_symbols = set()
            for df in new_data_frames:
                all_new_symbols.update(df['symbol'].tolist())
            self._update_symbol_sector_map(all_new_symbols)

            # 3. Pre-fetch delivery data
            try:
                from .delivery import NSEDeliveryManager
                deliv_mgr = NSEDeliveryManager()
                for d in missing_dates:
                    dt_obj = datetime.datetime.strptime(d, "%Y-%m-%d").date()
                    deliv_mgr.get_delivery_data(dt_obj)
                self.log(f"✓ Proactively pre-cached delivery files for {len(missing_dates)} dates.")
            except Exception as e_deliv:
                self.log(f"Delivery pre-cache notice: {e_deliv}")

            # 4. Sync benchmark series to match new universe dates (with fail-closed validation)
            sync_res = self.sync_benchmark()
            if sync_res.get("status") not in ["SUCCESS", "UP_TO_DATE"]:
                self.log(f"CRITICAL: Benchmark sync failed ({sync_res.get('message')}). Retaining existing valid benchmark; downstream components will FAIL CLOSED.")
                return {
                    "status": AutoFetchStatus.VALIDATION_FAILURE.value,
                    "benchmark_status": sync_res.get("status"),
                    "dates_fetched": len(new_data_frames),
                    "actions_applied": actions_applied,
                    "start_date": missing_dates[0],
                    "end_date": missing_dates[-1],
                    "message": f"Benchmark sync failed: {sync_res.get('message')}"
                }
            
        except Exception as e:
            write_conn.rollback()
            self.log(f"Error during db update: {e}")
            return {"status": AutoFetchStatus.DATA_INVALID.value, "message": str(e)}
        finally:
            write_conn.close()
            
        return {
            "status": AutoFetchStatus.UPDATED.value,
            "benchmark_status": sync_res.get("status"),
            "dates_fetched": len(new_data_frames),
            "actions_applied": actions_applied,
            "start_date": missing_dates[0] if missing_dates else None,
            "end_date": missing_dates[-1] if missing_dates else None
        }

    def sync_benchmark(self, target_date: Optional[str] = None) -> Dict:
        """
        Ensures data/benchmark_nifty500.csv is in sync with universe.db or target_date.
        Strict Fail-Closed Architecture:
          - Validates all prices are strictly finite, positive, and non-NaN.
          - Rejects partial gaps, future dates, and corrupt schema.
          - Atomic replacement via temporary file swap (preserves valid cache on failure).
          - Returns explicit machine-readable status (SUCCESS, UP_TO_DATE, FAILED, INVALID).
        """
        import os
        bench_csv = self.base_dir / "data" / "benchmark_nifty500.csv"
        if not bench_csv.exists():
            return {"status": BenchmarkSyncResult.FAILED.value, "code": "FILE_NOT_FOUND", "message": "benchmark CSV not found"}

        try:
            b_df = pd.read_csv(bench_csv)
            b_df["date"] = b_df["date"].astype(str)
            max_bench_date = b_df["date"].max()

            missing_dates = []
            if target_date is not None:
                target_str = str(target_date).strip()[:10]
                if target_str <= max_bench_date:
                    return {"status": BenchmarkSyncResult.UP_TO_DATE.value, "dates_added": 0, "max_date": max_bench_date}
                try:
                    cal = _de.load_trading_calendar()
                    missing_dates = [d for d in cal if max_bench_date < d <= target_str and d not in _de.KNOWN_NSE_HOLIDAYS]
                except Exception:
                    missing_dates = []
                if not missing_dates:
                    try:
                        conn = _de.get_connection(read_only=True, reuse=True)
                        cursor = conn.cursor()
                        cursor.execute("SELECT DISTINCT date FROM prices WHERE date > ? AND date <= ? ORDER BY date ASC;", (max_bench_date, target_str))
                        missing_dates = [r[0] for r in cursor.fetchall() if r[0] not in _de.KNOWN_NSE_HOLIDAYS]
                    except Exception:
                        pass
                if not missing_dates:
                    cur_d = datetime.datetime.strptime(max_bench_date, "%Y-%m-%d").date() + datetime.timedelta(days=1)
                    t_d = datetime.datetime.strptime(target_str, "%Y-%m-%d").date()
                    while cur_d <= t_d:
                        d_str = cur_d.strftime("%Y-%m-%d")
                        if cur_d.weekday() < 5 and d_str not in _de.KNOWN_NSE_HOLIDAYS:
                            missing_dates.append(d_str)
                        cur_d += datetime.timedelta(days=1)
            else:
                try:
                    conn = _de.get_connection(read_only=True, reuse=True)
                    cursor = conn.cursor()
                    cursor.execute("SELECT DISTINCT date FROM prices WHERE date > ? ORDER BY date ASC;", (max_bench_date,))
                    missing_dates = [r[0] for r in cursor.fetchall() if r[0] not in _de.KNOWN_NSE_HOLIDAYS]
                except Exception:
                    missing_dates = []

            if not missing_dates:
                return {"status": BenchmarkSyncResult.UP_TO_DATE.value, "dates_added": 0, "max_date": max_bench_date}

            self.log(f"Syncing benchmark for {len(missing_dates)} missing dates: {missing_dates}")
            new_rows = []

            # 1. Primary Source: Official NSE daily index reports
            nse_rows = []
            session = self._get_session()
            for d in missing_dates:
                try:
                    d_dt = datetime.datetime.strptime(d, "%Y-%m-%d")
                    url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d_dt.strftime('%d%m%Y')}.csv"
                    resp = session.get(url, timeout=10)
                    if resp.status_code == 200 and resp.content:
                        idf = pd.read_csv(io.BytesIO(resp.content))
                        idf.columns = [c.strip().upper() for c in idf.columns]
                        n500_match = idf[idf["INDEX NAME"].astype(str).str.strip().str.upper() == "NIFTY 500"]
                        if not n500_match.empty and "CLOSING INDEX VALUE" in n500_match.columns:
                            c_val = float(str(n500_match["CLOSING INDEX VALUE"].iloc[0]).replace(",", "").strip())
                            if np.isfinite(c_val) and c_val > 0:
                                nse_rows.append({"date": d, "close": c_val})
                except Exception as e_nse:
                    self.log(f"Notice: Official NSE index fetch for {d} returned: {e_nse}")

            if len(nse_rows) == len(missing_dates):
                self.log(f"✓ Acquired all {len(nse_rows)} benchmark closes directly from official NSE archives.")
                new_rows = nse_rows
            else:
                self.log(f"NSE direct index fetch got {len(nse_rows)}/{len(missing_dates)} dates. Falling back to Yahoo Finance ^CRSLDX.")
                try:
                    import yfinance as yf
                    ticker = yf.Ticker("^CRSLDX")
                    end_dt_str = (datetime.datetime.strptime(missing_dates[-1], "%Y-%m-%d") + datetime.timedelta(days=2)).strftime("%Y-%m-%d")
                    hist = ticker.history(start=missing_dates[0], end=end_dt_str)
                    if not hist.empty:
                        hist.index = hist.index.strftime("%Y-%m-%d")
                        for d in missing_dates:
                            if d in hist.index:
                                c_raw = hist.loc[d]["Close"]
                                c_val = float(c_raw.iloc[0] if isinstance(c_raw, pd.Series) else c_raw)
                                if not np.isfinite(c_val) or np.isnan(c_val) or c_val <= 0:
                                    self.log(f"CRITICAL: Non-finite or non-positive benchmark price ({c_val}) on {d}. Rejecting update.")
                                    return {"status": "INVALID", "code": "INVALID_PRICE_VALUE", "message": f"Non-finite/non-positive price on {d}"}
                                new_rows.append({"date": d, "close": c_val})
                except Exception as e_yf:
                    self.log(f"Error fetching official ^CRSLDX index from Yahoo Finance: {e_yf}")
                    return {"status": "FAILED", "code": "NETWORK_OR_API_ERROR", "message": str(e_yf)}

            # Invariant: Must fetch 100% of required missing dates (No silent partial gaps!)
            if len(new_rows) != len(missing_dates):
                missing_set = set(missing_dates) - {r["date"] for r in new_rows}
                self.log(f"CRITICAL: Partial benchmark response. Missing dates {missing_set}. Rejecting entire update to prevent gaps.")
                return {"status": "FAILED", "code": "PARTIAL_BENCHMARK_GAP", "message": f"Missing required dates: {missing_set}"}

            # Invariant: No unexpected future dates relative to current date
            today_str = datetime.date.today().strftime("%Y-%m-%d")
            for r in new_rows:
                if r["date"] > today_str:
                    self.log(f"CRITICAL: Future benchmark date detected: {r['date']} > {today_str}. Rejecting update.")
                    return {"status": "INVALID", "code": "FUTURE_DATE_REJECTED", "message": f"Future date {r['date']}"}

            new_df = pd.DataFrame(new_rows)
            updated_bdf = pd.concat([b_df, new_df], ignore_index=True)
            updated_bdf.drop_duplicates(subset=["date"], keep="last", inplace=True)
            updated_bdf.sort_values("date", inplace=True)
            updated_bdf.reset_index(drop=True, inplace=True)

            # Recompute continuous indicators strictly from validated prices
            updated_bdf["daily_return"] = updated_bdf["close"].pct_change().fillna(0.0)
            updated_bdf["ret_252"] = updated_bdf["close"].pct_change(252).fillna(0.0)
            updated_bdf["ema_20"] = updated_bdf["close"].ewm(span=20, adjust=False).mean()
            updated_bdf["ema_50"] = updated_bdf["close"].ewm(span=50, adjust=False).mean()
            updated_bdf["ema_200"] = updated_bdf["close"].ewm(span=200, adjust=False).mean()
            updated_bdf["high_252"] = updated_bdf["close"].rolling(252, min_periods=1).max()
            updated_bdf["drawdown"] = ((updated_bdf["close"] - updated_bdf["high_252"]) / updated_bdf["high_252"]) * 100.0

            # Pre-persistence Integrity Validation: Ensure zero NaNs in critical columns of updated rows
            tail_check = updated_bdf.iloc[-len(new_rows):]
            if tail_check[["close", "ema_20", "ema_200"]].isna().any().any():
                self.log("CRITICAL: Computed indicators contain NaNs. Rejecting update.")
                return {"status": "INVALID", "code": "CORRUPTED_INDICATOR_OUTPUT", "message": "Computed indicators contain NaN"}

            # ATOMIC WRITE PATTERN: Write to temporary file, validate, then atomic replace
            tmp_bench_csv = bench_csv.with_suffix(".csv.tmp")
            updated_bdf.to_csv(tmp_bench_csv, index=False)

            # Validate temporary file
            verify_df = pd.read_csv(tmp_bench_csv)
            if len(verify_df) != len(updated_bdf):
                if tmp_bench_csv.exists():
                    tmp_bench_csv.unlink()
                return {"status": "FAILED", "code": "ATOMIC_VERIFY_FAILED", "message": "Temporary file verification row count mismatch"}

            # Atomic replace
            os.replace(tmp_bench_csv, bench_csv)
            self.log(f"✓ benchmark_nifty500.csv atomically updated up to {missing_dates[-1]}")
            return {"status": "SUCCESS", "dates_added": len(new_rows), "max_date": missing_dates[-1]}
        except Exception as e:
            self.log(f"CRITICAL: Unhandled benchmark sync exception: {e}")
            if "tmp_bench_csv" in locals() and tmp_bench_csv.exists():
                tmp_bench_csv.unlink()
            return {"status": "FAILED", "code": "UNHANDLED_EXCEPTION", "message": str(e)}
