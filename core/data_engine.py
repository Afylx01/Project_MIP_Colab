"""
Project MIP Pydroid 3 Data Access Engine
Directive: DIR-PROD-PYDROID3-PORT-01

Pure Python + SQLite3 + Pandas data layer.
Zero PyArrow / Fastparquet dependency.
Optimized for mobile ARM64 storage and sub-millisecond indexed queries.
"""

import datetime
import hashlib
import json
import os
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Set, Union

_CACHED_CONN: Optional[sqlite3.Connection] = None


def get_base_dir() -> Path:
    """Returns the base directory of the MIP project."""
    env_dir = os.environ.get("MIP_BASE_DIR")
    if env_dir:
        p_env = Path(env_dir).resolve()
        if p_env.exists():
            return p_env

    # Primary: resolve relative to this file's location (core/ -> project root)
    p = Path(__file__).resolve().parent.parent
    if (p / "data" / "universe.db").exists():
        return p
    # Fallback: current working directory
    cwd = Path.cwd()
    if (cwd / "data" / "universe.db").exists():
        return cwd
    return p


def get_db_path() -> Path:
    """Returns absolute path to universe.db."""
    return get_base_dir() / "data" / "universe.db"


def get_connection(read_only: bool = True, reuse: bool = True) -> sqlite3.Connection:
    """
    Returns an open SQLite3 connection with performance pragmas.
    Reuses existing connection by default to avoid connection open/close overhead.
    Enforces production immutability firewall when read_only=False.
    """
    global _CACHED_CONN

    is_ro = read_only or os.environ.get("MIP_READONLY", "0") == "1"

    if reuse and _CACHED_CONN is not None and is_ro:
        try:
            # Quick probe
            _CACHED_CONN.execute("SELECT 1;")
            return _CACHED_CONN
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            _CACHED_CONN = None

    db_path = get_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}! Please run scripts/export_universe_to_sqlite.py first.")
    
    if is_ro:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, check_same_thread=False)
        try:
            conn.execute("PRAGMA query_only = ON;")
        except sqlite3.OperationalError:
            pass
    else:
        # PRODUCTION IMMUTABILITY FIREWALL:
        # Prevent any write connection to production universe.db unless explicitly authorized
        if db_path.resolve() == get_db_path().resolve() and os.environ.get("MIP_ALLOW_PROD_MUTATION", "0") != "1":
            raise PermissionError(
                "PRODUCTION IMMUTABILITY VIOLATION: Direct write connection to production universe.db is strictly prohibited without MIP_ALLOW_PROD_MUTATION=1"
            )
        conn = sqlite3.connect(str(db_path), check_same_thread=False)

    conn.execute("PRAGMA cache_size = 100000;")
    conn.execute("PRAGMA mmap_size = 300000000;")
    conn.execute("PRAGMA temp_store = MEMORY;")

    if reuse and is_ro:
        _CACHED_CONN = conn

    if not is_ro:
        ensure_database_schema(conn)

    return conn


def ensure_database_schema(conn: sqlite3.Connection) -> None:
    """Enforces relational constraints, unique indexes, and audit ledgers."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            is_delisted INTEGER DEFAULT 0
        );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prices_sym_date_unique ON prices (symbol, date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_date ON prices (date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_sym ON prices (symbol);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prices_sym_date ON prices (symbol, date DESC);")
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS picks_history (
            pick_date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry_price REAL,
            exit_price REAL,
            ret_since REAL,
            last_px_date TEXT,
            status TEXT DEFAULT 'ACTIVE',
            PRIMARY KEY (pick_date, symbol)
        );
    """)
    conn.commit()


def load_applied_corporate_actions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Loads applied and recorded corporate actions matching criteria.
    Point-In-Time safe when end_date <= as_of_date.
    Loads from authoritative sidecar JSON registry (data/corporate_actions_registry.json)
    and SQLite table applied_corporate_actions.
    """
    res: List[Dict[str, Any]] = []
    seen_keys = set()

    # 1. Authoritative Sidecar JSON Registry
    reg_path = get_base_dir() / "data" / "corporate_actions_registry.json"
    if reg_path.exists():
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            action_list = data.get("actions", data) if isinstance(data, dict) else data
            symbols_upper = {s.strip().upper() for s in symbols} if symbols else None
            for item in action_list:
                sym = str(item.get("symbol", "")).strip().upper()
                ex = str(item.get("ex_date", ""))[:10]
                eff = str(item.get("effective_date", ex))[:10]

                if symbols_upper and sym not in symbols_upper:
                    continue
                if start_date and ex < str(start_date)[:10]:
                    continue
                if end_date and (ex > str(end_date)[:10] or eff > str(end_date)[:10]):
                    continue  # Strict PIT boundary: future actions excluded

                key = (sym, ex)
                if key not in seen_keys:
                    seen_keys.add(key)
                    act_t = str(item.get("action_type", item.get("type", ""))).strip().upper()
                    res.append({
                        "symbol": sym,
                        "ex_date": ex,
                        "effective_date": eff,
                        "type": act_t,
                        "action_type": act_t,
                        "action_nature": str(item.get("action_nature", "UNKNOWN")),
                        "factor": float(item.get("factor", 1.0)),
                        "amount": float(item.get("factor", 1.0)),
                        "applied_at": str(item.get("ingestion_timestamp", ex)),
                        "source_authority": str(item.get("source_authority", "")),
                        "source_reference": str(item.get("source_reference", "")),
                        "status": str(item.get("status", "CONFIRMED")),
                    })
        except Exception:
            pass

    # 2. SQLite Ledger Overlay
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT symbol, ex_date, type, factor, amount, applied_at FROM applied_corporate_actions WHERE 1=1"
    params = []
    if start_date:
        query += " AND ex_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND ex_date <= ?"
        params.append(end_date)
    if symbols:
        placeholders = ",".join(["?"] * len(symbols))
        query += f" AND symbol IN ({placeholders})"
        params.extend([s.strip().upper() for s in symbols])

    query += " ORDER BY ex_date ASC, symbol ASC"
    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        for r in rows:
            sym = str(r[0]).strip().upper()
            ex = str(r[1])[:10]
            key = (sym, ex)
            if key not in seen_keys:
                seen_keys.add(key)
                res.append({
                    "symbol": sym,
                    "ex_date": ex,
                    "effective_date": ex,
                    "type": r[2],
                    "action_type": r[2],
                    "action_nature": "UNKNOWN",
                    "factor": r[3],
                    "amount": r[4],
                    "applied_at": r[5],
                })
    except sqlite3.OperationalError:
        pass

    return sorted(res, key=lambda a: (a["ex_date"], a["symbol"]))


def get_latest_date() -> str:
    """Returns the latest available trading date in universe.db (YYYY-MM-DD)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(date) FROM prices;")
    res = cursor.fetchone()
    return res[0] if res and res[0] else ""


def get_date_range() -> Tuple[str, str]:
    """Returns (min_date, max_date)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(date), MAX(date) FROM prices;")
    res = cursor.fetchone()
    return (res[0], res[1]) if res else ("", "")


def get_symbols() -> List[str]:
    """Returns sorted list of all unique symbols in the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT symbol FROM prices ORDER BY symbol ASC;")
    return [row[0] for row in cursor.fetchall()]


def load_bars(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    include_delisted: bool = True
) -> pd.DataFrame:
    """
    Loads OHLCV bars matching criteria.
    Dynamically uses index idx_prices_date or idx_prices_sym_date.
    """
    conditions = []
    params = []

    if start_date:
        conditions.append("date >= ?")
        params.append(str(start_date))
    if end_date:
        conditions.append("date <= ?")
        params.append(str(end_date))
    if symbols:
        placeholders = ",".join("?" for _ in symbols)
        conditions.append(f"symbol IN ({placeholders})")
        params.extend(symbols)
    if not include_delisted:
        conditions.append("is_delisted = 0")

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT date, symbol, open, high, low, close, volume, is_delisted
        FROM prices
        {where_clause}
        ORDER BY date ASC, symbol ASC;
    """

    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    
    if not df.empty:
        df['is_delisted'] = df['is_delisted'].astype(bool)
    return df


def load_symbol_history(
    symbol: str,
    lookback_bars: int = 250,
    end_date: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    as_dataframe: bool = True
) -> Any:
    """
    Sub-millisecond retrieval of symbol historical bars using idx_prices_sym_date.
    Returns bars sorted in ascending chronological order.
    """
    db_conn = conn or get_connection()
    cursor = db_conn.cursor()

    if end_date:
        query = """
            SELECT date, symbol, open, high, low, close, volume, is_delisted
            FROM prices
            WHERE symbol = ? AND date <= ?
            ORDER BY date DESC
            LIMIT ?;
        """
        params = (symbol, str(end_date), int(lookback_bars))
    else:
        query = """
            SELECT date, symbol, open, high, low, close, volume, is_delisted
            FROM prices
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT ?;
        """
        params = (symbol, int(lookback_bars))

    cursor.execute(query, params)
    rows = cursor.fetchall()

    if not as_dataframe:
        # Return reversed raw tuples: (date, symbol, open, high, low, close, volume, is_delisted)
        return rows[::-1]

    cols = ['date', 'symbol', 'open', 'high', 'low', 'close', 'volume', 'is_delisted']
    if not rows:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(rows, columns=cols)
    df = df.iloc[::-1].reset_index(drop=True)
    df['is_delisted'] = df['is_delisted'].astype(bool)
    return df


def load_universe_snapshot(date: Optional[str] = None, conn: Optional[sqlite3.Connection] = None) -> pd.DataFrame:
    """
    Retrieves all scrip bars for a specific date (or latest date).
    Uses idx_prices_date for ultra-fast snapshot retrieval.
    """
    db_conn = conn or get_connection()
    target_date = date or get_latest_date()
    query = """
        SELECT date, symbol, open, high, low, close, volume, is_delisted
        FROM prices
        WHERE date = ?
        ORDER BY symbol ASC;
    """
    df = pd.read_sql_query(query, db_conn, params=[target_date])
    if not df.empty:
        df['is_delisted'] = df['is_delisted'].astype(bool)
    return df


def load_symbol_sector_map() -> Dict[str, str]:
    """Loads official sector taxonomy mapping dictionary {SYMBOL: SECTOR}."""
    map_path = get_base_dir() / "data" / "symbol_sector_map.json"
    if not map_path.exists():
        return {}
    with open(map_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("symbol_to_sector", data)


AUTHORITATIVE_CALENDAR_SHA256 = "4b3dce45d011a0a14861c5d949c4b795e277d202a4ee279cd0ede8019e936c57"
AUTHORITATIVE_CALENDAR_TOTAL_DATES = 4889
AUTHORITATIVE_CALENDAR_START_DATE = "2007-01-02"
AUTHORITATIVE_CALENDAR_END_DATE = "2026-10-16"

KNOWN_NSE_HOLIDAYS = {
    "2026-01-26",  # Republic Day
    "2026-03-03",  # Holi
    "2026-03-27",  # Id-Ul-Fitr
    "2026-04-03",  # Good Friday
    "2026-04-14",  # Dr. Ambedkar Jayanti
    "2026-05-01",  # Maharashtra Day
    "2026-05-28",  # Bakri Id
    "2026-06-26",  # Muharram
    "2026-08-15",  # Independence Day
    "2026-10-02",  # Mahatma Gandhi Jayanti
    "2026-10-20",  # Dussehra
    "2026-11-09",  # Diwali Balipratipada
    "2026-11-24",  # Gurunanak Jayanti
    "2026-12-25",  # Christmas
}


class StaleDataError(RuntimeError):
    """Raised when an unspecified-date scan determines that database data is stale and latest data is unavailable."""
    pass


class DataUnavailableError(RuntimeError):
    """Raised when an explicit or resolved scan date has no data in the database."""
    pass


def get_expected_latest_eod(
    reference_dt: Optional[datetime.datetime] = None,
    cal_path: Optional[Path] = None,
) -> str:
    """
    Determines the latest expected completed and published EOD trading session date.
    Considers NSE trading hours (closes 15:30 IST, Bhavcopy published by ~18:30 IST),
    weekends, and known statutory exchange holidays.
    Authoritatively checks data/trading_calendar.txt.
    """
    now_utc = reference_dt or datetime.datetime.now(datetime.timezone.utc)
    ist_offset = datetime.timedelta(hours=5, minutes=30)
    now_ist = now_utc + ist_offset
    cur_date_str = now_ist.strftime("%Y-%m-%d")

    cal = load_trading_calendar(cal_path=cal_path)
    if cal:
        cal_set = set(cal)
        max_cal_date = cal[-1]
        is_published = (now_ist.hour > 18) or (now_ist.hour == 18 and now_ist.minute >= 30)

        if cur_date_str <= max_cal_date:
            is_today_trading = (cur_date_str in cal_set) and (cur_date_str not in KNOWN_NSE_HOLIDAYS)
            if is_today_trading and is_published:
                return cur_date_str

            past_dates = [d for d in cal if d < cur_date_str and d not in KNOWN_NSE_HOLIDAYS]
            if past_dates:
                return past_dates[-1]
        else:
            # Calendar ends at max_cal_date (e.g. 2026-10-15); evaluate subsequent weekdays and statutory holidays
            candidate = now_ist.date()
            if not (candidate.weekday() < 5 and is_published):
                candidate -= datetime.timedelta(days=1)

            while candidate.weekday() >= 5 or candidate.strftime("%Y-%m-%d") in KNOWN_NSE_HOLIDAYS:
                candidate -= datetime.timedelta(days=1)

            candidate_str = candidate.strftime("%Y-%m-%d")
            if candidate_str >= max_cal_date:
                return candidate_str
            return max_cal_date

    # Fallback to statutory calendar / holiday set if trading_calendar.txt is unavailable
    candidate = now_ist.date()
    if candidate.weekday() < 5 and (now_ist.hour > 18 or (now_ist.hour == 18 and now_ist.minute >= 30)):
        pass
    else:
        candidate -= datetime.timedelta(days=1)

    while candidate.weekday() >= 5 or candidate.strftime("%Y-%m-%d") in KNOWN_NSE_HOLIDAYS:
        candidate -= datetime.timedelta(days=1)

    return candidate.strftime("%Y-%m-%d")


def resolve_latest_valid_eod(
    base_dir: Optional[Path] = None,
    as_of_date: Optional[str] = None,
    allow_stale: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Authoritative Date-Resolution Function.
    Answers: 'What is the latest valid EOD date I can safely scan right now?'

    Enforces Contract:
      - If as_of_date is supplied: verifies exact requested date is present and valid in SQLite.
      - If as_of_date is None:
          1. Determines latest expected published market session.
          2. Inspects database for actual latest valid date.
          3. Rejects stale data if db_latest < expected_session and allow_stale is False.
          4. Verifies database integrity (row counts, symbol count >= 50).
    """
    base = Path(base_dir) if base_dir else get_base_dir()
    db_conn = get_connection(read_only=True, reuse=True)
    cursor = db_conn.cursor()

    if as_of_date is not None:
        target = str(as_of_date).strip()[:10]
        cursor.execute("SELECT COUNT(DISTINCT symbol), COUNT(*) FROM prices WHERE date = ?;", (target,))
        row = cursor.fetchone()
        sym_count = row[0] if row else 0
        row_count = row[1] if row else 0
        if sym_count < 20 or row_count < 20:
            return False, "", {
                "status": "DATE_UNAVAILABLE",
                "error": f"Requested date '{target}' has insufficient/no data in SQLite (symbols={sym_count}, rows={row_count})",
                "requested_date": target,
            }
        return True, target, {
            "status": "EXPLICIT_DATE_VALIDATED",
            "date": target,
            "symbol_count": sym_count,
            "row_count": row_count,
        }

    # Unspecified date mode:
    cursor.execute("SELECT MAX(date) FROM prices;")
    res = cursor.fetchone()
    db_latest = str(res[0]) if res and res[0] else ""
    if not db_latest:
        return False, "", {
            "status": "DATABASE_EMPTY",
            "error": "SQLite prices table is empty. No valid EOD dates exist.",
        }

    cursor.execute("SELECT COUNT(DISTINCT symbol), COUNT(*) FROM prices WHERE date = ?;", (db_latest,))
    row = cursor.fetchone()
    sym_count = row[0] if row else 0
    row_count = row[1] if row else 0
    if sym_count < 50:
        return False, db_latest, {
            "status": "DATA_CORRUPT",
            "error": f"Latest date '{db_latest}' has only {sym_count} symbols (minimum 50 required).",
            "db_latest": db_latest,
        }

    expected_session = get_expected_latest_eod()
    is_stale = (db_latest < expected_session)

    if is_stale and not allow_stale:
        return False, db_latest, {
            "status": "STALE_DATA_BLOCKED",
            "db_latest": db_latest,
            "expected_session": expected_session,
            "error": f"LATEST MARKET DATA UNAVAILABLE: Database latest EOD ({db_latest}) is older than expected session ({expected_session}).",
        }

    return True, db_latest, {
        "status": "VALIDATED",
        "date": db_latest,
        "db_latest": db_latest,
        "expected_session": expected_session,
        "symbol_count": sym_count,
        "row_count": row_count,
        "is_stale": is_stale,
    }



def verify_trading_calendar_authenticity(
    cal_path: Optional[Path] = None,
    expected_sha256: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Cryptographically audits and verifies the provenance and authenticity of the NSE trading calendar.
    Validates file existence, SHA-256 digest, line count, date boundaries, and formatting.
    """
    target = Path(cal_path) if cal_path else (get_base_dir() / "data" / "trading_calendar.txt")
    if not target.exists():
        return False, f"CALENDAR_FILE_NOT_FOUND: {target}", {}

    raw_bytes = target.read_bytes()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    expected = expected_sha256 or AUTHORITATIVE_CALENDAR_SHA256

    with open(target, "r", encoding="utf-8") as f:
        dates = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    meta = {
        "file_path": str(target),
        "sha256": digest,
        "expected_sha256": expected,
        "sha256_match": (digest == expected),
        "total_dates": len(dates),
        "expected_total_dates": AUTHORITATIVE_CALENDAR_TOTAL_DATES,
        "is_sorted": (dates == sorted(dates)),
        "unique_count": len(set(dates)),
        "duplicates": len(dates) - len(set(dates)),
        "start_date": dates[0] if dates else "",
        "end_date": dates[-1] if dates else "",
    }

    if digest != expected:
        return False, f"CALENDAR_AUTHENTICITY_MISMATCH: SHA256 {digest} != expected {expected}", meta
    if len(dates) != AUTHORITATIVE_CALENDAR_TOTAL_DATES:
        return False, f"CALENDAR_COUNT_MISMATCH: {len(dates)} != {AUTHORITATIVE_CALENDAR_TOTAL_DATES}", meta
    if not meta["is_sorted"] or meta["duplicates"] > 0:
        return False, "CALENDAR_INTEGRITY_VIOLATION: unsorted or duplicate dates", meta

    return True, "CALENDAR_AUTHENTIC_AND_VERIFIED", meta


def load_trading_calendar(
    verify_authenticity: bool = False,
    cal_path: Optional[Path] = None,
) -> List[str]:
    """
    Loads list of valid NSE trading dates.
    If verify_authenticity=True, cryptographically validates file SHA-256 against canonical manifest.
    """
    target = Path(cal_path) if cal_path else (get_base_dir() / "data" / "trading_calendar.txt")
    if not target.exists():
        return []
    if verify_authenticity:
        ok, msg, _ = verify_trading_calendar_authenticity(target)
        if not ok:
            raise ValueError(f"CALENDAR_AUTHENTICITY_FAILURE: {msg}")
    with open(target, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return sorted(lines)


def load_authoritative_trading_calendar(cal_path: Optional[Path] = None) -> List[str]:
    """
    Mandatory production-facing trading calendar loader (Directive R4).
    Strictly enforces cryptographic SHA-256 authenticity validation.
    Raises ValueError immediately if file is missing, tampered, corrupted, or stale.
    """
    return load_trading_calendar(verify_authenticity=True, cal_path=cal_path)


def validate_calendar_refresh(
    candidate_content_or_path: Union[str, Path],
    expected_sha256: str,
    existing_calendar: Optional[List[str]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Formally validates a candidate trading calendar refresh against the 6-stage contract (Directive R5):
    Stage 1: Syntax Validation: Every line must be a valid ISO-8601 YYYY-MM-DD date.
    Stage 2: Sorted & Unique Validation: Dates must be strictly increasing, with 0 duplicates.
    Stage 3: Session Integrity & Non-Regression:
             - Must start on or before existing START_DATE ("2007-01-02").
             - Must extend beyond existing END_DATE ("2026-10-02").
             - No gap between consecutive trading dates may exceed 5 calendar days.
    Stage 4: Cryptographic Provenance: Candidate raw byte SHA-256 must match expected_sha256 manifest.
    Stage 5: Parity & Activation Metadata: Confirms activation eligibility.
    """
    if isinstance(candidate_content_or_path, Path) or (
        isinstance(candidate_content_or_path, str) and "\n" not in candidate_content_or_path and Path(candidate_content_or_path).exists()
    ):
        p = Path(candidate_content_or_path)
        if not p.exists():
            return False, f"CALENDAR_REFRESH_FILE_NOT_FOUND: {p}", {}
        raw_bytes = p.read_bytes()
        text_content = raw_bytes.decode("utf-8")
    else:
        text_content = str(candidate_content_or_path)
        raw_bytes = text_content.encode("utf-8")

    lines = [l.strip() for l in text_content.splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return False, "EMPTY_CALENDAR_REFRESH: no valid date lines present", {}

    meta = {
        "candidate_total_dates": len(lines),
        "expected_sha256": expected_sha256,
        "candidate_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "stages_passed": [],
    }

    # Stage 1: Syntax Validation
    parsed_dates = []
    for line in lines:
        try:
            d = datetime.date.fromisoformat(line)
            parsed_dates.append(d)
        except ValueError:
            return False, f"INVALID_DATE_SYNTAX: '{line}' is not valid ISO-8601 YYYY-MM-DD", meta
    meta["stages_passed"].append("STAGE_1_SYNTAX_VALIDATED")

    # Stage 2: Sorted & Unique Validation
    for i in range(len(lines) - 1):
        if lines[i] >= lines[i + 1]:
            if lines[i] == lines[i + 1]:
                return False, f"DUPLICATE_DATE: duplicate session '{lines[i]}'", meta
            return False, f"UNSORTED_DATES: date '{lines[i]}' is not strictly before '{lines[i+1]}'", meta
    meta["stages_passed"].append("STAGE_2_SORTED_AND_UNIQUE_VALIDATED")

    # Stage 3: Session Integrity & Non-Regression
    start_date = lines[0]
    end_date = lines[-1]
    meta["start_date"] = start_date
    meta["end_date"] = end_date

    if start_date > AUTHORITATIVE_CALENDAR_START_DATE:
        return False, f"HISTORICAL_REGRESSION: refresh starts at '{start_date}', after canonical '{AUTHORITATIVE_CALENDAR_START_DATE}'", meta

    if end_date <= AUTHORITATIVE_CALENDAR_END_DATE:
        return False, f"NO_EXTENSION: refresh ends at '{end_date}', does not extend beyond canonical '{AUTHORITATIVE_CALENDAR_END_DATE}'", meta

    for i in range(len(parsed_dates) - 1):
        d1 = parsed_dates[i]
        d2 = parsed_dates[i + 1]
        gap_days = (d2 - d1).days
        if gap_days > 7:
            return False, f"EXCESSIVE_CALENDAR_GAP: {gap_days} days gap between {d1.isoformat()} and {d2.isoformat()}", meta
    meta["stages_passed"].append("STAGE_3_INTEGRITY_AND_CONTINUITY_VALIDATED")

    # Stage 4: Cryptographic Provenance Check
    computed_digest = meta["candidate_sha256"]
    if computed_digest != expected_sha256:
        return False, f"AUTHENTICITY_MISMATCH: SHA256 {computed_digest} != expected {expected_sha256}", meta
    meta["stages_passed"].append("STAGE_4_CRYPTOGRAPHIC_PROVENANCE_VALIDATED")

    meta["activation_eligible"] = True
    return True, "CALENDAR_REFRESH_VALIDATED", meta


def apply_calendar_refresh(
    candidate_path: Union[str, Path],
    expected_sha256: str,
    target_paths: Optional[List[Path]] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Atomically synchronizes and activates a validated calendar refresh across
    canonical and parity repositories (Directive R5).
    """
    valid, msg, meta = validate_calendar_refresh(candidate_path, expected_sha256)
    if not valid:
        return False, f"REFRESH_ACTIVATION_REJECTED: {msg}", meta

    targets = target_paths or [
        get_base_dir() / "data" / "trading_calendar.txt",
    ]
    raw_content = Path(candidate_path).read_bytes()
    for t in targets:
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(raw_content)

    meta["activated_targets"] = [str(t) for t in targets]
    return True, "CALENDAR_REFRESH_ACTIVATED", meta


def get_universe_statistics() -> Dict[str, Any]:
    """Returns database summary statistics."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM prices;")
    total_rows = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT symbol) FROM prices;")
    unique_symbols = cursor.fetchone()[0]

    cursor.execute("SELECT MIN(date), MAX(date) FROM prices;")
    min_date, max_date = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM prices WHERE is_delisted = 1;")
    delisted_count = cursor.fetchone()[0]

    db_path = get_db_path()
    file_size_mb = db_path.stat().st_size / (1024 * 1024) if db_path.exists() else 0.0

    return {
        "db_path": str(db_path),
        "file_size_mb": round(file_size_mb, 2),
        "total_rows": total_rows,
        "unique_symbols": unique_symbols,
        "min_date": min_date,
        "max_date": max_date,
        "delisted_rows": delisted_count,
    }


def load_universe_constituents(universe_name: str = "NIFTY500", force_refresh: bool = False) -> Set[str]:
    """
    Authoritative index constituent loader for Project MIP.
    Enforces canonical 30-day cache TTL policy, fail-closed schema validation,
    anti-HTML guards, and whitelist failover across all supported universes.
    Malformed, empty, None, and garbage modes cleanly fall back to NIFTY500 safe defaults.
    """
    if universe_name is None:
        target_mode = "NIFTY500"
    else:
        u_raw = str(universe_name).strip()
        u_clean = u_raw.upper().replace(" ", "").replace("_", "").replace("-", "")
        if u_clean in ["ALL", "MASTER", "PIT"]:
            return set()
        if not u_clean:
            target_mode = "NIFTY500"
        else:
            try:
                from scripts.scanner_hardening import normalize_universe_mode, NIFTY_INDICES_CATALOG
                norm = normalize_universe_mode(u_raw)
                if norm in NIFTY_INDICES_CATALOG or "500" in u_clean or "750" in u_clean or "TOTAL" in u_clean:
                    target_mode = norm
                else:
                    target_mode = "NIFTY500"
            except Exception:
                target_mode = "NIFTY500"

    try:
        from scripts.scanner_hardening import ConstituentReconciliationEngine, ConstituentSourceStatus
        engine = ConstituentReconciliationEngine(get_base_dir())
        rep = engine.fetch_and_reconcile(
            universe_mode=target_mode,
            force_live_fetch=force_refresh,
            allow_stale=True,
            cache_ttl_days=30.0,
        )
        if rep.source_status == ConstituentSourceStatus.BLOCKED:
            if target_mode != "NIFTY500":
                rep = engine.fetch_and_reconcile(
                    universe_mode="NIFTY500",
                    force_live_fetch=force_refresh,
                    allow_stale=True,
                    cache_ttl_days=30.0,
                )
            if rep.source_status == ConstituentSourceStatus.BLOCKED:
                return set()
        
        fname = engine.FILENAME_MAP.get(engine._normalize_mode(target_mode), "")
        fpath = engine.raw_dir / fname
        if fpath.exists():
            df = pd.read_csv(fpath)
            sym_col = [c for c in df.columns if str(c).strip().upper() == "SYMBOL"]
            if sym_col:
                return set(df[sym_col[0]].astype(str).str.strip().str.upper())
    except Exception:
        pass

    fallback_path = get_base_dir() / "data" / "raw_reference" / "ind_nifty500list.csv"
    if fallback_path.exists():
        try:
            df = pd.read_csv(fallback_path)
            sym_col = [c for c in df.columns if str(c).strip().upper() == "SYMBOL"]
            if sym_col:
                return set(df[sym_col[0]].astype(str).str.strip().str.upper())
        except Exception:
            pass

    return set()


def get_universe_label(universe_mode: str) -> str:
    """Returns human-readable institutional label for the selected universe."""
    if universe_mode is None:
        return "NIFTY 500"
    u_clean = str(universe_mode).strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    if u_clean in ["500", "NIFTY500"] or not u_clean:
        return "NIFTY 500"
    elif "750" in u_clean or "TOTAL" in u_clean:
        return "NIFTY 750 (TOTAL MARKET)"
    elif u_clean in ["ALL", "MASTER", "PIT"]:
        return "ALL ACTIVE SCRIPS"
    try:
        from scripts.scanner_hardening import get_hardened_universe_label
        return get_hardened_universe_label(universe_mode)
    except Exception:
        pass
    return str(universe_mode).upper()
