"""
Project MIP Pydroid 3: Portfolio Manager & Dynamic Position Sizing
Directive: DIR-PROD-PYDROID3-PARITY-01 (MIP-1 v5.5.1 Parity) & Phase 5 Audit Hardening

Implements:
  - Strict Downstream Actionable BUY Safety Firewall (validate_candidate_safety).
  - Exit Buffer (Rank 40) & Trend Exit Rules for existing holdings.
  - Fail-Closed Market Regime Filter (Pause new entries if Benchmark < 20 EMA or Invalid).
  - Ticker Transition & Canonical Identity Governance (SecurityIdentityManager deduplication).
  - Deterministic Sector Concentration Hard Cap (Max 2 stocks per industry/sector).
  - Safe Sector Normalization (NaN / null / empty mapped to "OTHER").
  - Whole-Share Integer ATR-14 Volatility Risk Parity Position Sizing (No fractional shares).
  - Indian statutory frictions (STT, Exchange Turnover, GST, Stamp Duty, Brokerage).
  - Institutional PortfolioState and Cash Conservation Ledger.
  - Complete Rebalance Orders Ledger with deterministic audit trails.
"""

import copy
from dataclasses import dataclass, field
import datetime
from enum import Enum
import hashlib
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set
import numpy as np
import pandas as pd

try:
    from zoneinfo import ZoneInfo
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

from .data_engine import get_base_dir, get_connection, get_latest_date
from .identity import SecurityIdentityManager
from .reason_codes import ScannerReasonCode

FRICTIONS = {
    'stt_rate': 0.001,               # STT @ 0.1% (buy side delivery)
    'exchange_turnover': 0.0000345,  # Exchange turnover @ 0.00345%
    'gst_rate': 0.18,                # GST @ 18% on brokerage + turnover
    'stamp_duty': 0.00015,           # Stamp duty @ 0.015%
    'brokerage_rate': 0.0003,        # Discount broker @ 0.03%
}


def normalize_session_date(dt_input: Any, exchange_tz: Any = None) -> str:
    """
    Normalizes any datetime, date, timestamp, or ISO string to the canonical
    exchange session date (YYYY-MM-DD) in Asia/Kolkata (IST).
    Guarantees:
      - Same market instant -> same exchange session date.
      - Converts UTC, positive/negative offsets, DST inputs to IST.
      - Validates calendar validity (leap years, month days).
    """
    if dt_input is None or (isinstance(dt_input, float) and math.isnan(dt_input)):
        return ""
    if isinstance(dt_input, datetime.date) and not isinstance(dt_input, datetime.datetime):
        return dt_input.strftime("%Y-%m-%d")

    s = str(dt_input).strip()
    if not s:
        return ""

    tz = exchange_tz or IST_TZ

    # Check for simple YYYY-MM-DD string
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        try:
            valid_d = datetime.date.fromisoformat(s)
            return valid_d.strftime("%Y-%m-%d")
        except ValueError:
            return ""

    # Handle ISO datetime strings
    try:
        clean_s = s
        if clean_s.endswith('Z') or clean_s.endswith('z'):
            clean_s = clean_s[:-1] + '+00:00'
        dt = datetime.datetime.fromisoformat(clean_s)
        if dt.tzinfo is None:
            return dt.strftime("%Y-%m-%d")
        dt_local = dt.astimezone(tz)
        return dt_local.strftime("%Y-%m-%d")
    except Exception:
        try:
            ts = pd.to_datetime(s)
            if ts.tzinfo is not None:
                ts = ts.tz_convert("Asia/Kolkata")
            return ts.strftime("%Y-%m-%d")
        except Exception:
            return ""


def is_trading_session(
    date_str: str,
    trading_calendar: Optional[List[str]] = None,
    fail_closed: bool = False,
) -> bool:
    """
    Validates whether date_str is an active market trading session.
    If trading_calendar is provided, verifies presence in calendar.
    Otherwise:
      - If fail_closed=True: returns False (fail-closed, no weekday fallback).
      - If fail_closed=False: utility fallback to weekday (Monday-Friday, 0-4).
    """
    clean_d = normalize_session_date(date_str)
    if not clean_d:
        return False
    if trading_calendar:
        valid_dates = {s for s in trading_calendar if isinstance(s, str) and normalize_session_date(s)}
        return clean_d in valid_dates
    if fail_closed:
        return False
    try:
        dt = datetime.date.fromisoformat(clean_d)
        return dt.weekday() < 5
    except Exception:
        return False


def get_next_trading_session(
    date_str: str,
    trading_calendar: Optional[List[str]] = None,
    fail_closed: bool = False,
) -> str:
    """
    Returns the next valid exchange trading session date strictly after date_str.
    If trading_calendar is provided, resolves next date from sorted unique valid dates.
    Otherwise:
      - If fail_closed=True: returns "" (fail-closed, no weekday fallback).
      - If fail_closed=False: utility fallback to weekday (Monday-Friday).
    """
    clean_d = normalize_session_date(date_str)
    if not clean_d:
        return ""
    if trading_calendar:
        valid_dates = [s for s in trading_calendar if isinstance(s, str) and normalize_session_date(s)]
        for s in sorted(set(valid_dates)):
            if s > clean_d:
                return s
        return ""
    if fail_closed:
        return ""
    try:
        dt = datetime.date.fromisoformat(clean_d)
        curr = dt + datetime.timedelta(days=1)
        while curr.weekday() >= 5:
            curr += datetime.timedelta(days=1)
        return curr.strftime("%Y-%m-%d")
    except Exception:
        return ""


def is_trading_session_fail_closed(
    date_str: str,
    trading_calendar: Optional[List[str]] = None,
) -> bool:
    """Explicitly fail-closed trading session validator with zero weekday fallback."""
    return is_trading_session(date_str, trading_calendar, fail_closed=True)


def get_next_trading_session_fail_closed(
    date_str: str,
    trading_calendar: Optional[List[str]] = None,
) -> str:
    """Explicitly fail-closed next-session resolver with zero weekday fallback."""
    return get_next_trading_session(date_str, trading_calendar, fail_closed=True)


def normalize_sector(val: Any) -> str:
    """
    Normalizes sector/industry string into canonical upper-case token.
    Converts None, NaN, whitespace, and 'NAN' into 'OTHER' to prevent sector cap bypass.
    """
    if val is None or pd.isna(val):
        return "OTHER"
    s = str(val).strip().upper()
    return s if s and s not in ("NAN", "NONE", "NULL", "UNDEFINED") else "OTHER"


def validate_candidate_safety(row: pd.Series, top_n: int = 20) -> Tuple[bool, str, str]:
    """
    Institutional downstream safety firewall for candidate order generation.
    Guarantees that no unadjusted corporate action, degraded security,
    defensive/bearish signal, unranked/buffer candidate, or non-finite price
    can generate an actionable BUY ticket.
    """
    sym = str(row.get("symbol", "UNKNOWN")).strip().upper()

    # 1. Price Integrity & Finite Positive Value
    cand_price = row.get("close")
    if cand_price is None or pd.isna(cand_price):
        return False, f"Close price for {sym} is NaN or None", ScannerReasonCode.PORTFOLIO_INVALID_PRICE.value
    try:
        p = float(cand_price)
        if not math.isfinite(p) or p <= 0:
            return False, f"Close price {p} for {sym} is non-positive or non-finite", ScannerReasonCode.PORTFOLIO_INVALID_PRICE.value
    except (ValueError, TypeError):
        return False, f"Close price for {sym} cannot be converted to float", ScannerReasonCode.PORTFOLIO_INVALID_PRICE.value

    # 2. Allow Buy Flag (Strict Boolean Identity)
    allow_buy = row.get("allow_buy")
    if allow_buy is not True:
        return False, f"Candidate {sym} has allow_buy={allow_buy} (must be strictly True)", ScannerReasonCode.PORTFOLIO_CANDIDATE_UNSAFE.value

    # 3. Signal Type
    sig_type = str(row.get("signal_type", "BUY")).strip().upper()
    if sig_type in ("BLOCKED_HOLD", "BEAR_HOLD", "BUFFER_HOLD", "REVIEW_REQUIRED", "BLOCKED", "UNSAFE"):
        return False, f"Candidate {sym} has non-buy signal_type: {sig_type}", ScannerReasonCode.PORTFOLIO_CANDIDATE_UNSAFE.value

    # 4. Corporate Action Status (Strict Whitelist: CLEAN or RESOLVED)
    ca_status = str(row.get("corporate_action_status", "")).strip().upper()
    if ca_status not in ("CLEAN", "RESOLVED"):
        return False, f"Candidate {sym} has unverified corporate_action_status: '{ca_status}' (must be in {{'CLEAN', 'RESOLVED'}})", ScannerReasonCode.CORPORATE_ACTION_REVIEW_REQUIRED.value

    # 5. Security Health State (Strict Whitelist: HEALTHY)
    sec_health = str(row.get("security_health", "")).strip().upper()
    if sec_health != "HEALTHY":
        return False, f"Candidate {sym} has non-healthy security_health: '{sec_health}' (must be HEALTHY)", ScannerReasonCode.PORTFOLIO_CANDIDATE_UNSAFE.value

    # 6. Reason Code Check
    r_code = str(row.get("reason_code", "PASS")).strip().upper()
    if r_code not in ("PASS", "NONE", "NAN", ""):
        return False, f"Candidate {sym} has non-passing reason_code: {r_code}", ScannerReasonCode.PORTFOLIO_CANDIDATE_UNSAFE.value

    # 7. Rank Rule for New Entries: Rank must be <= top_n (Exit buffer 21-40 cannot be bought as new entry)
    cand_rank = row.get("rank")
    if cand_rank is not None and not pd.isna(cand_rank):
        try:
            r_int = int(cand_rank)
            if r_int > top_n:
                return False, f"Candidate {sym} rank #{r_int} exceeds top_n={top_n} allocation threshold (Hold-only buffer)", ScannerReasonCode.PORTFOLIO_RANK_EXCEEDED.value
        except (ValueError, TypeError):
            pass

    return True, "SAFE", ScannerReasonCode.PASS.value


class OrderStatus(str, Enum):
    """Institutional Order Lifecycle State Machine."""
    CREATED = "CREATED"
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"


LEGAL_ORDER_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
    OrderStatus.CREATED: {OrderStatus.PENDING, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.REPLACED},
    OrderStatus.PENDING: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED, OrderStatus.REPLACED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.REPLACED},
    OrderStatus.FILLED: set(),      # Terminal
    OrderStatus.CANCELLED: set(),   # Terminal
    OrderStatus.REJECTED: set(),    # Terminal
    OrderStatus.EXPIRED: set(),     # Terminal
    OrderStatus.REPLACED: set(),    # Terminal
}


def validate_order_transition(current_status: OrderStatus, target_status: OrderStatus) -> Tuple[bool, str]:
    """
    Validates whether a transition from current_status to target_status is legal.
    """
    c = OrderStatus(current_status) if not isinstance(current_status, OrderStatus) else current_status
    t = OrderStatus(target_status) if not isinstance(target_status, OrderStatus) else target_status
    allowed = LEGAL_ORDER_TRANSITIONS.get(c, set())
    if t in allowed:
        return True, f"LEGAL_TRANSITION: {c.value} -> {t.value}"
    return False, f"ILLEGAL_TRANSITION: Cannot transition order from {c.value} to {t.value}"


class OrderSide(str, Enum):
    """Institutional Order Side."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Order:
    """Formal institutional Order ticket with complete audit state transitions."""
    order_id: str
    symbol: str
    security_id: str
    side: OrderSide
    requested_shares: int
    order_date: str
    limit_price: Optional[float] = None
    filled_shares: int = 0
    status: OrderStatus = OrderStatus.CREATED
    reason: str = ""
    reason_code: str = ScannerReasonCode.PASS.value
    rejection_reason: Optional[str] = None
    cancellation_reason: Optional[str] = None
    expiration_reason: Optional[str] = None
    replacement_reason: Optional[str] = None
    replaced_by_order_id: Optional[str] = None
    replaces_order_id: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    expected_execution_date: Optional[str] = None
    allow_same_day: bool = False


@dataclass
class OrderFill:
    """Formal institutional Execution Fill with idempotency key and exact friction tracking."""
    fill_id: str                          # Globally unique fill execution ID / Idempotency Key
    order_id: str
    symbol: str
    security_id: str
    side: OrderSide
    fill_shares: int
    fill_price: float
    fill_date: str                        # Market session of execution (e.g. T+1 Open)
    frictions: float = 0.0                # Statutory frictions (STT, exchange, brokerage, GST, stamp)
    slippage: float = 0.0                 # Slippage impact
    timestamp: str = ""


@dataclass
class Position:
    """Institutional Position Record with full lifecycle audit metadata."""
    security_id: str
    symbol: str
    sector: str
    shares: int
    cost_basis: float          # Total capital deployed including frictions
    buy_price: float
    entry_date: str
    last_price: float = 0.0


class PortfolioState:
    """
    Formal institutional portfolio accounting state machine and NAV ledger.
    Maintains cash conservation, whole-share integer constraints,
    strict fill idempotency, overfill prevention, order lifecycle transitions,
    and exact reconciliation between cash, frictions, realized PnL, and NAV.
    """

    def __init__(
        self,
        initial_capital: float = 1_000_000.0,
        as_of_date: str = "",
        trading_calendar: Optional[List[str]] = None,
        strict_chronology: bool = False,
        enforce_trading_calendar: bool = False,
        verify_calendar_authenticity: Optional[bool] = None,
    ):
        self.initial_capital: float = float(initial_capital)
        self.cash: float = float(initial_capital)
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.processed_fill_ids: Set[str] = set()
        self.trade_history: List[Dict] = []
        self.total_frictions_paid: float = 0.0
        self.realized_pnl: float = 0.0
        self.as_of_date: str = normalize_session_date(as_of_date) if as_of_date else ""
        if verify_calendar_authenticity is None:
            self.verify_calendar_authenticity: bool = bool(enforce_trading_calendar)
        else:
            self.verify_calendar_authenticity = bool(verify_calendar_authenticity)

        if trading_calendar is not None:
            self.trading_calendar: List[str] = list(trading_calendar)
            if self.verify_calendar_authenticity and len(self.trading_calendar) > 0:
                from .data_engine import AUTHORITATIVE_CALENDAR_SHA256
                reconstructed = "\n".join(self.trading_calendar) + "\n"
                digest = hashlib.sha256(reconstructed.encode("utf-8")).hexdigest()
                if digest != AUTHORITATIVE_CALENDAR_SHA256:
                    raise ValueError(f"CALENDAR_AUTHENTICITY_MISMATCH: Provided calendar list fails cryptographic authenticity ({digest} != {AUTHORITATIVE_CALENDAR_SHA256})")
        elif enforce_trading_calendar:
            try:
                from .data_engine import load_authoritative_trading_calendar
                self.trading_calendar = load_authoritative_trading_calendar()
            except Exception:
                self.trading_calendar = []
        else:
            self.trading_calendar = []
        self.strict_chronology: bool = bool(strict_chronology)
        self.enforce_trading_calendar: bool = bool(enforce_trading_calendar)

    def get_holdings_dict(self) -> Dict[str, int]:
        """Returns {symbol: shares} for all open positive positions."""
        return {sym: pos.shares for sym, pos in self.positions.items() if pos.shares > 0}

    def get_market_value(self, price_map: Optional[Dict[str, float]] = None) -> float:
        """Calculates total mark-to-market equity value across open positions."""
        price_map = price_map or {}
        total_mv = 0.0
        for sym, pos in self.positions.items():
            px = price_map.get(sym, pos.last_price or pos.buy_price)
            total_mv += pos.shares * px
        return round(total_mv, 2)

    def get_nav(self, price_map: Optional[Dict[str, float]] = None) -> float:
        """Calculates total Net Asset Value (Cash + Mark-to-Market Equity)."""
        return round(self.cash + self.get_market_value(price_map), 2)

    def create_order(
        self,
        symbol: str,
        security_id: str,
        side: Any,
        requested_shares: int,
        order_date: str,
        limit_price: Optional[float] = None,
        reason: str = "",
        reason_code: str = ScannerReasonCode.PASS.value,
        order_id: Optional[str] = None,
        expected_execution_date: Optional[str] = None,
        allow_same_day: Optional[bool] = None,
    ) -> Order:
        """Instantiates and registers a new order in CREATED state."""
        if type(requested_shares) is not int or requested_shares <= 0:
            raise ValueError(f"requested_shares must be a positive integer, got {requested_shares}")

        clean_order_date = normalize_session_date(order_date)
        if not clean_order_date:
            raise ValueError(f"Invalid order_date: {order_date}")

        clean_exec_date = normalize_session_date(expected_execution_date) if expected_execution_date else None

        if allow_same_day is None:
            if clean_exec_date is not None:
                eff_allow_same_day = False
            elif self.strict_chronology or self.enforce_trading_calendar:
                eff_allow_same_day = False
            else:
                eff_allow_same_day = True
        else:
            eff_allow_same_day = bool(allow_same_day)

        oid = order_id or f"ORD_{clean_order_date}_{symbol}_{len(self.orders)+1:04d}"
        side_val = OrderSide(side) if not isinstance(side, OrderSide) else side

        order = Order(
            order_id=oid,
            symbol=symbol.strip().upper(),
            security_id=security_id.strip(),
            side=side_val,
            requested_shares=requested_shares,
            order_date=clean_order_date,
            limit_price=limit_price,
            filled_shares=0,
            status=OrderStatus.CREATED,
            reason=reason,
            reason_code=reason_code,
            created_at=str(order_date),
            updated_at=str(order_date),
            expected_execution_date=clean_exec_date,
            allow_same_day=eff_allow_same_day,
        )
        self.orders[oid] = order
        return order

    def submit_order(self, order_id: str) -> Tuple[bool, str]:
        """Transitions order from CREATED to PENDING state."""
        order = self.orders.get(order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: {order_id}"
        if order.status != OrderStatus.CREATED:
            return False, f"INVALID_TRANSITION: Cannot submit order with status {order.status.value}"
        order.status = OrderStatus.PENDING
        order.updated_at = datetime.datetime.now().isoformat()
        return True, "SUBMITTED"

    def cancel_order(self, order_id: str, reason: str = "") -> Tuple[bool, str]:
        """Cancels a created, pending, or partially filled order. Has zero effect on cash or holdings."""
        order = self.orders.get(order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: {order_id}"
        if order.status not in (OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            return False, f"INVALID_TRANSITION: Cannot cancel order in status {order.status.value}"
        order.status = OrderStatus.CANCELLED
        order.cancellation_reason = reason
        order.updated_at = datetime.datetime.now().isoformat()
        return True, "CANCELLED"

    def reject_order(self, order_id: str, reason: str = "") -> Tuple[bool, str]:
        """Rejects an unexecuted order (CREATED or PENDING). Has zero effect on cash or holdings."""
        order = self.orders.get(order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: {order_id}"
        if order.status == OrderStatus.PARTIALLY_FILLED:
            return False, "INVALID_TRANSITION: Cannot reject partially filled order; use cancel_order instead"
        if order.status not in (OrderStatus.CREATED, OrderStatus.PENDING):
            return False, f"INVALID_TRANSITION: Cannot reject order with status {order.status.value}"
        order.status = OrderStatus.REJECTED
        order.rejection_reason = reason
        order.updated_at = datetime.datetime.now().isoformat()
        return True, "REJECTED"

    def expire_order(self, order_id: str, reason: str = "") -> Tuple[bool, str]:
        """
        Transitions an active order (CREATED, PENDING, PARTIALLY_FILLED) to EXPIRED.
        Has zero effect on cash, holdings, or historical ledger.
        """
        order = self.orders.get(order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: {order_id}"
        if order.status not in (OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            return False, f"INVALID_TRANSITION: Cannot expire order in status {order.status.value}"
        order.status = OrderStatus.EXPIRED
        order.expiration_reason = reason
        order.updated_at = datetime.datetime.now().isoformat()
        return True, "EXPIRED"

    def replace_order(
        self,
        order_id: str,
        new_shares: int,
        new_price: Optional[float] = None,
        reason: str = "",
    ) -> Tuple[Optional[Order], str]:
        """
        Replaces an active order with a fresh order, maintaining strict state isolation.
        The old order is transitioned to terminal REPLACED.
        The replacement order is created in CREATED state with:
          - New unique order_id
          - Requested shares = new_shares
          - Zero filled shares (no inheritance)
          - Zero cost basis / fill price (no inheritance)
          - Zero inherited financial mutations or trade history
        """
        order = self.orders.get(order_id)
        if not order:
            return None, f"ORDER_NOT_FOUND: {order_id}"
        if order.status not in (OrderStatus.CREATED, OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            return None, f"INVALID_TRANSITION: Cannot replace order in status {order.status.value}"
        if type(new_shares) is not int or new_shares <= 0:
            return None, f"INVALID_SHARES: new_shares {new_shares} must be positive integer"
        if new_price is not None:
            try:
                p_val = float(new_price)
                if not math.isfinite(p_val) or p_val <= 0:
                    return None, f"INVALID_PRICE: new_price {new_price} must be positive finite float"
            except (ValueError, TypeError):
                return None, f"INVALID_PRICE: new_price {new_price} cannot be converted to float"
        else:
            p_val = order.limit_price

        import uuid
        new_order_id = f"ORD_{uuid.uuid4().hex[:12].upper()}"
        while new_order_id in self.orders or new_order_id == order.order_id:
            new_order_id = f"ORD_{uuid.uuid4().hex[:12].upper()}"

        now_str = datetime.datetime.now().isoformat()

        # Transition old order to terminal REPLACED
        order.status = OrderStatus.REPLACED
        order.replacement_reason = reason
        order.replaced_by_order_id = new_order_id
        order.updated_at = now_str

        # Spawn isolated replacement order
        new_order = Order(
            order_id=new_order_id,
            symbol=order.symbol,
            security_id=order.security_id,
            side=order.side,
            requested_shares=new_shares,
            order_date=order.order_date,
            limit_price=p_val,
            filled_shares=0,
            status=OrderStatus.CREATED,
            reason=f"REPLACEMENT_OF_{order.order_id}: {reason}".strip(),
            reason_code=order.reason_code,
            created_at=now_str,
            updated_at=now_str,
            expected_execution_date=order.expected_execution_date,
            allow_same_day=order.allow_same_day,
            replaces_order_id=order.order_id,
        )
        self.orders[new_order.order_id] = new_order
        return new_order, "REPLACED"

    def transition_order(self, order_id: str, target_status: OrderStatus, reason: str = "") -> Tuple[bool, str]:
        """Formal generic state transition validator."""
        order = self.orders.get(order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: {order_id}"
        target = OrderStatus(target_status) if not isinstance(target_status, OrderStatus) else target_status
        allowed = LEGAL_ORDER_TRANSITIONS.get(order.status, set())
        if target not in allowed:
            return False, f"INVALID_TRANSITION: Cannot transition from {order.status.value} to {target.value}"
        order.status = target
        if target == OrderStatus.CANCELLED:
            order.cancellation_reason = reason
        elif target == OrderStatus.REJECTED:
            order.rejection_reason = reason
        elif target == OrderStatus.EXPIRED:
            order.expiration_reason = reason
        elif target == OrderStatus.REPLACED:
            order.replacement_reason = reason
        order.updated_at = datetime.datetime.now().isoformat()
        return True, f"TRANSITIONED_TO_{target.value}"

    def apply_fill(self, fill: OrderFill) -> Tuple[bool, str]:
        """
        Applies execution fill to portfolio state with:
          1. Strict Idempotency: duplicate fill IDs are rejected without state mutation.
          2. Valid Order State: order must be in PENDING or PARTIALLY_FILLED.
          3. Fill Geometry & Numerics Gate: positive integer shares, finite positive price, non-negative finite frictions.
          4. Temporal Chronology & Session Gate:
             - fill_date >= order_date (R1-A)
             - fill_date != order_date if same-day execution forbidden (R1-B)
             - fill_date == expected_execution_date if next-session contract specified (R1-C, R1-D, R1-F)
             - trading day validation if calendar enforced (R1-E)
          5. Overfill Protection: cumulative fills cannot exceed requested shares.
          6. Cash Conservation: cash must remain >= 0 (no borrowing).
          7. Proportional Accounting: accurate realized PnL and remaining cost basis.
          8. Atomicity: on ANY failure, financial state is 100% unchanged.
        """
        # 1. Idempotency Gate
        if fill.fill_id in self.processed_fill_ids:
            return False, f"DUPLICATE_FILL_REJECTED: fill_id {fill.fill_id} already processed"

        # 2. Order State Gate
        order = self.orders.get(fill.order_id)
        if not order:
            return False, f"ORDER_NOT_FOUND: order_id {fill.order_id}"
        if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED):
            return False, f"INVALID_ORDER_STATE: cannot fill order in status {order.status.value}"

        # 3. Fill Geometry & Numerics Gate
        if type(fill.fill_shares) is not int or fill.fill_shares <= 0:
            return False, f"INVALID_FILL_SHARES: {fill.fill_shares} must be positive integer"
        try:
            px = float(fill.fill_price)
            if not math.isfinite(px) or px <= 0.0:
                return False, f"INVALID_FILL_PRICE: {fill.fill_price} must be positive finite"
        except (ValueError, TypeError):
            return False, f"INVALID_FILL_PRICE: {fill.fill_price} cannot be converted to float"

        # 3b. Frictions & Slippage Numerics Gate
        try:
            fric = float(fill.frictions)
            slip = float(fill.slippage)
            if not math.isfinite(fric) or fric < 0.0:
                return False, f"INVALID_FRICTIONS: {fill.frictions} must be non-negative finite float"
            if not math.isfinite(slip) or slip < 0.0:
                return False, f"INVALID_SLIPPAGE: {fill.slippage} must be non-negative finite float"
        except (ValueError, TypeError):
            return False, "INVALID_FRICTIONS_OR_SLIPPAGE: frictions and slippage must be numeric"

        # 4. Temporal Chronology & Session Gate
        clean_fill_date = normalize_session_date(fill.fill_date)
        if not clean_fill_date:
            return False, f"INVALID_FILL_DATE: fill_date '{fill.fill_date}' is invalid or empty"

        order_d = normalize_session_date(order.order_date)

        # R1-A: fill_date < order_date is temporally impossible
        if clean_fill_date < order_d:
            return False, f"CHRONOLOGY_VIOLATION: fill_date {clean_fill_date} is prior to order_date {order_d}"

        # R1-B: same-day fill check
        if clean_fill_date == order_d and not order.allow_same_day:
            return False, f"SAME_DAY_EXECUTION_FORBIDDEN: fill_date {clean_fill_date} equals order_date {order_d} under canonical next-session contract"

        # R1-C, R1-D, R1-F: expected execution date checks
        if order.expected_execution_date:
            expected_d = normalize_session_date(order.expected_execution_date)
            if clean_fill_date > expected_d:
                return False, f"DELAYED_FILL_REJECTED: fill_date {clean_fill_date} exceeds expected execution date {expected_d}"
            if clean_fill_date < expected_d:
                return False, f"PREMATURE_FILL_REJECTED: fill_date {clean_fill_date} is prior to expected execution date {expected_d}"

        # R1-E: non-trading day check & calendar fail-closed contract
        if self.enforce_trading_calendar:
            if not self.trading_calendar:
                return False, "TRADING_CALENDAR_UNAVAILABLE: authoritative calendar required but missing or empty"
            if not is_trading_session_fail_closed(clean_fill_date, self.trading_calendar):
                return False, f"NON_TRADING_DAY_REJECTED: fill_date {clean_fill_date} is a weekend or non-trading holiday"
        elif self.trading_calendar and len(self.trading_calendar) > 0:
            if not is_trading_session_fail_closed(clean_fill_date, self.trading_calendar):
                return False, f"NON_TRADING_DAY_REJECTED: fill_date {clean_fill_date} is a weekend or non-trading holiday"

        # 5. Overfill Protection Gate
        remaining_shares = order.requested_shares - order.filled_shares
        if fill.fill_shares > remaining_shares:
            return False, f"OVERFILL_BLOCKED: fill_shares ({fill.fill_shares}) exceeds remaining order quantity ({remaining_shares})"

        # 6. Financial Balance & Position Ledger
        total_fric = fric + slip
        gross_value = fill.fill_shares * px
        side_val = OrderSide(fill.side) if not isinstance(fill.side, OrderSide) else fill.side

        if side_val == OrderSide.BUY:
            total_cost = gross_value + total_fric
            if round(self.cash - total_cost, 4) < -1e-4:
                return False, f"INSUFFICIENT_CASH: available cash ({self.cash:.2f}) < required ({total_cost:.2f})"
            self.cash -= total_cost
            self.total_frictions_paid += total_fric

            pos = self.positions.get(fill.symbol)
            if pos:
                new_shares = pos.shares + fill.fill_shares
                new_cost = pos.cost_basis + total_cost
                new_buy_px = ((pos.buy_price * pos.shares) + (px * fill.fill_shares)) / new_shares
                self.positions[fill.symbol] = Position(
                    security_id=fill.security_id,
                    symbol=fill.symbol,
                    sector=pos.sector,
                    shares=new_shares,
                    cost_basis=new_cost,
                    buy_price=new_buy_px,
                    entry_date=pos.entry_date,
                    last_price=px,
                )
            else:
                self.positions[fill.symbol] = Position(
                    security_id=fill.security_id,
                    symbol=fill.symbol,
                    sector="OTHER",
                    shares=fill.fill_shares,
                    cost_basis=total_cost,
                    buy_price=px,
                    entry_date=clean_fill_date,
                    last_price=px,
                )
        elif side_val == OrderSide.SELL:
            pos = self.positions.get(fill.symbol)
            if not pos or pos.shares < fill.fill_shares:
                avail = pos.shares if pos else 0
                return False, f"INSUFFICIENT_SHARES: available ({avail}) < sell ({fill.fill_shares})"

            net_proceeds = gross_value - total_fric
            self.cash += net_proceeds
            self.total_frictions_paid += total_fric

            # Gross realized PnL calculation
            trade_gross_pnl = (px - pos.buy_price) * fill.fill_shares
            self.realized_pnl += trade_gross_pnl

            # Proportional cost basis deduction
            allocated_cost = pos.cost_basis * (fill.fill_shares / pos.shares)
            rem_shares = pos.shares - fill.fill_shares
            if rem_shares > 0:
                rem_cost = pos.cost_basis - allocated_cost
                self.positions[fill.symbol] = Position(
                    security_id=pos.security_id,
                    symbol=pos.symbol,
                    sector=pos.sector,
                    shares=rem_shares,
                    cost_basis=rem_cost,
                    buy_price=pos.buy_price,
                    entry_date=pos.entry_date,
                    last_price=px,
                )
            else:
                del self.positions[fill.symbol]

        # 7. Advance Order Status
        order.filled_shares += fill.fill_shares
        if order.filled_shares >= order.requested_shares:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        order.updated_at = datetime.datetime.now().isoformat()

        # 8. Record Idempotency & Immutable Audit Trace (R1-G)
        self.processed_fill_ids.add(fill.fill_id)
        trade_record = {
            "fill_id": fill.fill_id,
            "order_id": fill.order_id,
            "symbol": fill.symbol,
            "side": side_val.value,
            "shares": fill.fill_shares,
            "price": px,
            "frictions": fric,
            "slippage": slip,
            "date": clean_fill_date,
        }
        self.trade_history.append(trade_record)
        return True, "FILL_APPLIED"

    def get_trade_history(self) -> List[Dict[str, Any]]:
        """Returns deep-copied immutable list of executed trades."""
        return [copy.deepcopy(t) for t in self.trade_history]

    def execute_rebalance_orders(
        self,
        orders_df: pd.DataFrame,
        execution_prices: Dict[str, float],
        exec_date: str,
        slippage_rate: float = 0.0005,
    ) -> List[Dict[str, Any]]:
        """
        Executes a batch of rebalance orders applying canonical same-day sequencing:
        1. All SELL orders execute first, crediting cash proceeds.
        2. All BUY orders execute second using available cash.
        Guarantees order independence from dataframe row order.
        """
        results = []
        if orders_df.empty:
            return results

        if self.enforce_trading_calendar:
            if not self.trading_calendar:
                raise ValueError("TRADING_CALENDAR_UNAVAILABLE: authoritative calendar required but missing or empty")
            clean_exec_date = normalize_session_date(exec_date)
            if not is_trading_session_fail_closed(clean_exec_date, self.trading_calendar):
                raise ValueError(f"NON_TRADING_DAY_REJECTED: exec_date '{exec_date}' is not an authoritative trading session")

        clean_orders = orders_df[orders_df["action"].isin(["BUY", "SELL"])].copy()
        sells = clean_orders[clean_orders["action"] == "SELL"]
        buys = clean_orders[clean_orders["action"] == "BUY"]

        # Phase 1: SELLs executed first
        for _, row in sells.iterrows():
            sym = str(row["symbol"]).strip().upper()
            sec_id = str(row.get("security_id", f"SEC_{sym}"))
            shares = int(row["target_shares"]) if row.get("target_shares") and int(row["target_shares"]) > 0 else (self.positions.get(sym).shares if sym in self.positions else 0)
            if shares <= 0:
                continue

            px = execution_prices.get(sym, float(row.get("close_price", 0.0)))
            if px <= 0:
                continue

            trade_val = shares * px
            fric_dict = FRICTIONS
            stt = trade_val * fric_dict['stt_rate']
            exchange = trade_val * fric_dict['exchange_turnover']
            brokerage = trade_val * fric_dict['brokerage_rate']
            gst = (brokerage + exchange) * fric_dict['gst_rate']
            stamp = trade_val * fric_dict['stamp_duty']
            total_fric = stt + exchange + brokerage + gst + stamp
            slip = trade_val * slippage_rate

            order_d = normalize_session_date(row.get("as_of_date", exec_date)) or exec_date
            clean_exec_date = normalize_session_date(exec_date) or exec_date
            allow_sd = (order_d == clean_exec_date)

            order = self.create_order(
                symbol=sym,
                security_id=sec_id,
                side=OrderSide.SELL,
                requested_shares=shares,
                order_date=order_d,
                expected_execution_date=clean_exec_date,
                allow_same_day=allow_sd,
            )
            self.submit_order(order.order_id)
            fill = OrderFill(
                fill_id=f"FILL_{clean_exec_date}_{order.order_id}_01",
                order_id=order.order_id,
                symbol=sym,
                security_id=sec_id,
                side=OrderSide.SELL,
                fill_shares=shares,
                fill_price=px,
                fill_date=clean_exec_date,
                frictions=total_fric,
                slippage=slip,
            )
            ok, msg = self.apply_fill(fill)
            if not ok:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = msg
            results.append({"order_id": order.order_id, "symbol": sym, "side": "SELL", "success": ok, "message": msg})

        # Phase 2: BUYs executed second
        for _, row in buys.iterrows():
            sym = str(row["symbol"]).strip().upper()
            sec_id = str(row.get("security_id", f"SEC_{sym}"))
            shares = int(row["target_shares"])
            if shares <= 0:
                continue

            px = execution_prices.get(sym, float(row.get("close_price", 0.0)))
            if px <= 0:
                continue

            trade_val = shares * px
            fric_dict = FRICTIONS
            stt = trade_val * fric_dict['stt_rate']
            exchange = trade_val * fric_dict['exchange_turnover']
            brokerage = trade_val * fric_dict['brokerage_rate']
            gst = (brokerage + exchange) * fric_dict['gst_rate']
            stamp = trade_val * fric_dict['stamp_duty']
            total_fric = stt + exchange + brokerage + gst + stamp
            slip = trade_val * slippage_rate

            order_d = normalize_session_date(row.get("as_of_date", exec_date)) or exec_date
            clean_exec_date = normalize_session_date(exec_date) or exec_date
            allow_sd = (order_d == clean_exec_date)

            order = self.create_order(
                symbol=sym,
                security_id=sec_id,
                side=OrderSide.BUY,
                requested_shares=shares,
                order_date=order_d,
                expected_execution_date=clean_exec_date,
                allow_same_day=allow_sd,
            )
            self.submit_order(order.order_id)
            fill = OrderFill(
                fill_id=f"FILL_{clean_exec_date}_{order.order_id}_01",
                order_id=order.order_id,
                symbol=sym,
                security_id=sec_id,
                side=OrderSide.BUY,
                fill_shares=shares,
                fill_price=px,
                fill_date=clean_exec_date,
                frictions=total_fric,
                slippage=slip,
            )
            ok, msg = self.apply_fill(fill)
            if not ok:
                order.status = OrderStatus.REJECTED
                order.rejection_reason = msg
            results.append({"order_id": order.order_id, "symbol": sym, "side": "BUY", "success": ok, "message": msg})

        return results

    def snapshot(self, as_of_date: str = "") -> "PortfolioState":
        """Returns an immutable deep-copied snapshot of portfolio state as of date T."""
        snap_state = copy.deepcopy(self)
        snap_state.as_of_date = as_of_date or self.as_of_date
        return snap_state

    def reconcile_accounting(self, price_map: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
        """
        Verifies cash conservation and NAV accounting identity:
        Starting Capital + Realized PnL + Unrealized PnL - Total Frictions == NAV.
        Residual must strictly be < 1e-4.
        """
        price_map = price_map or {}
        unrealized_pnl = 0.0
        for sym, pos in self.positions.items():
            px = price_map.get(sym, pos.last_price or pos.buy_price)
            unrealized_pnl += (px - pos.buy_price) * pos.shares

        expected_nav = self.initial_capital + self.realized_pnl + unrealized_pnl - self.total_frictions_paid
        actual_nav = self.get_nav(price_map)
        residual = abs(actual_nav - expected_nav)

        is_conserved = residual < 1e-4
        return {
            "initial_capital": self.initial_capital,
            "cash": round(self.cash, 2),
            "market_value": self.get_market_value(price_map),
            "actual_nav": actual_nav,
            "expected_nav": round(expected_nav, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_frictions_paid": round(self.total_frictions_paid, 2),
            "residual": round(residual, 6),
            "is_conserved": is_conserved,
        }


EMPTY_ORDERS_COLS = [
    'action', 'security_id', 'symbol', 'sector', 'close_price', 'atr_14', 'stop_loss',
    'target_shares', 'target_value', 'risk_allocated', 'stt', 'exchange_turnover',
    'brokerage', 'gst', 'stamp_duty', 'total_friction', 'total_cost', 'reason',
    'reason_code', 'as_of_date', 'source_signal'
]


class PortfolioManager:
    """Manages portfolio rebalance tickets, ATR risk parity sizing, and sector caps."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        portfolio_state: Optional["PortfolioState"] = None,
        cash: Optional[float] = None,
    ):
        self.base_dir = Path(base_dir) if base_dir else get_base_dir()
        self.reports_dir = self.base_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.identity_mgr = SecurityIdentityManager()
        self.portfolio_state = portfolio_state
        self.cash = float(cash) if cash is not None else None

    def log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] PORTFOLIO: {msg}")

    def load_screener_output(self) -> pd.DataFrame:
        """Reads reports/screener_output_live.csv sorted by volar_score descending."""
        screener_path = self.reports_dir / "screener_output_live.csv"
        if not screener_path.exists():
            raise FileNotFoundError(f"Screener output not found at {screener_path}")

        df = pd.read_csv(screener_path)
        if 'volar_score' in df.columns:
            df = df.sort_values(by='volar_score', ascending=False).reset_index(drop=True)
        return df

    def compute_frictions(self, trade_value: float) -> dict:
        """Computes Indian statutory market frictions for the given trade value."""
        stt = trade_value * FRICTIONS['stt_rate']
        exchange_turnover = trade_value * FRICTIONS['exchange_turnover']
        brokerage = trade_value * FRICTIONS['brokerage_rate']
        gst = (brokerage + exchange_turnover) * FRICTIONS['gst_rate']
        stamp_duty = trade_value * FRICTIONS['stamp_duty']
        total_friction = stt + exchange_turnover + brokerage + gst + stamp_duty

        return {
            'stt': stt,
            'exchange_turnover': exchange_turnover,
            'brokerage': brokerage,
            'gst': gst,
            'stamp_duty': stamp_duty,
            'total_friction': total_friction,
        }

    def compute_atr_14(self, symbols: List[str], as_of_date: str) -> Dict[str, float]:
        """Calculates 14-day Average True Range (ATR_14) from SQLite prices."""
        conn = get_connection(read_only=True, reuse=True)
        atr_dict = {}

        if not symbols:
            return {}

        query = """
            SELECT symbol, date, high, low, close
            FROM prices
            WHERE symbol IN ({seq}) AND date <= ?
            ORDER BY symbol, date DESC
        """.format(seq=','.join(['?'] * len(symbols)))

        params = list(symbols) + [as_of_date]
        df = pd.read_sql_query(query, conn, params=params)

        if df.empty:
            return {s: 0.0 for s in symbols}

        for sym, grp in df.groupby("symbol"):
            grp = grp.sort_values("date").tail(25)
            if len(grp) < 15:
                atr_dict[sym] = float(grp["close"].iloc[-1] * 0.03) if not grp.empty else 0.0
                continue

            h = grp["high"].values
            l = grp["low"].values
            c = grp["close"].values
            prev_c = np.roll(c, 1)
            prev_c[0] = c[0]

            tr1 = h - l
            tr2 = np.abs(h - prev_c)
            tr3 = np.abs(l - prev_c)
            tr = np.maximum(tr1, np.maximum(tr2, tr3))

            atr_14 = float(np.mean(tr[-14:]))
            atr_dict[sym] = round(atr_14, 2)

        return atr_dict

    def generate_rebalance_orders(
        self,
        capital: Optional[float] = None,
        top_n: Optional[int] = None,
        max_per_sector: Optional[int] = None,
        sizing_mode: Optional[str] = None,
        risk_per_trade_pct: Optional[float] = None,
        current_holdings: Optional[dict] = None,
        exit_buffer_rank: int = 40,
        regime_active: bool = True,
        as_of_date: Optional[str] = None,
        allow_research_overrides: bool = False,
        cash: Optional[float] = None,
        portfolio_state: Optional[Any] = None,
    ) -> pd.DataFrame:
        """
        Generates rebalance orders applying:
          1. Exit Buffer (Rank 40) & Trend Exit Rules for existing holdings.
          2. Market Regime Filter (Pause new entries if Benchmark < 20 EMA or Invalid).
          3. Downstream Actionable BUY Safety Firewall (Blocks corrupted or blocked tickets).
          4. Ticker Transition & Canonical Identity Deduplication.
          5. Deterministic Sector Concentration Hard Cap (Max per sector, normalized).
          6. Whole-Share Integer ATR-14 Volatility Risk Parity (or Equal Weight) Position Sizing.
          7. Authoritative Net Asset Value (NAV) Derivation: NAV(T) = Cash(T) + sum_i (Shares_i * Close_i(T)).
          8. Indian Statutory Friction Deductions & Capital Budget Normalization.
        """
        eff_state = portfolio_state if portfolio_state is not None else getattr(self, "portfolio_state", None)
        if eff_state is not None:
            if current_holdings is None and hasattr(eff_state, "get_holdings_dict"):
                current_holdings = eff_state.get_holdings_dict()
            elif current_holdings is None and hasattr(eff_state, "positions"):
                current_holdings = {sym: pos.shares for sym, pos in eff_state.positions.items() if pos.shares > 0}
            if cash is None and hasattr(eff_state, "cash"):
                cash = float(eff_state.cash)
        elif cash is None and getattr(self, "cash", None) is not None:
            cash = float(self.cash)

        from .settings import load_investing_settings
        st = load_investing_settings(self.base_dir)

        # Validate explicit capital if supplied
        if capital is not None:
            capital = float(capital)
            if not math.isfinite(capital) or capital <= 0:
                raise ValueError(f"INVALID_CAPITAL: capital must be a positive finite number, got {capital}")
        elif cash is None:
            capital = float(st.get("capital", 1000000.0))
            if not math.isfinite(capital) or capital <= 0:
                raise ValueError(f"INVALID_CAPITAL: capital must be a positive finite number, got {capital}")

        if cash is not None:
            cash_val = float(cash)
            if not math.isfinite(cash_val) or cash_val < 0:
                raise ValueError(f"INVALID_CASH: cash must be a non-negative finite number, got {cash}")

        top_n = int(top_n if top_n is not None else st.get("top_n", 20))
        max_per_sector = int(max_per_sector if max_per_sector is not None else st.get("max_per_sector", 2))
        sizing_mode = str(sizing_mode if sizing_mode is not None else st.get("sizing_mode", "atr_risk_parity")).strip().lower()
        if sizing_mode not in ("atr_risk_parity", "equal_weight"):
            raise ValueError(f"INVALID_SIZING_MODE: '{sizing_mode}' is not supported. Must be 'atr_risk_parity' or 'equal_weight'.")

        risk_per_trade_pct = float(risk_per_trade_pct if risk_per_trade_pct is not None else st.get("risk_per_trade_pct", 1.0))
        if not math.isfinite(risk_per_trade_pct) or risk_per_trade_pct <= 0:
            raise ValueError(f"INVALID_RISK_PER_TRADE: risk_per_trade_pct must be a positive finite percentage, got {risk_per_trade_pct}")
        if abs(risk_per_trade_pct - 1.0) > 1e-6 and not allow_research_overrides:
            raise ValueError(
                f"PRODUCTION_RISK_OVERRIDE_REJECTED: Production execution strictly requires risk_per_trade_pct=1.0. "
                f"Resolved value is {risk_per_trade_pct}%. Research overrides require allow_research_overrides=True."
            )
        latest_date = str(as_of_date).strip()[:10] if as_of_date else get_latest_date()

        screener_df = self.load_screener_output()
        if screener_df.empty:
            self.log("No qualifying screener candidates found.")
            return pd.DataFrame(columns=EMPTY_ORDERS_COLS)

        current_holdings = current_holdings or {}

        # Evaluate Market Regime (Strictly Fail-Closed)
        is_bull = True
        if regime_active:
            from .benchmark_validator import evaluate_regime as eval_regime, BenchmarkRegimeStatus
            from .data_engine import load_authoritative_trading_calendar
            try:
                calendar = load_authoritative_trading_calendar()
            except Exception:
                calendar = None

            regime_res = eval_regime(
                as_of_date=latest_date,
                benchmark_csv_or_df=self.base_dir / "data" / "benchmark_nifty500.csv",
                trading_calendar=calendar,
            )
            is_bull = regime_res.allow_new_buys
            if not regime_res.is_valid or regime_res.status != BenchmarkRegimeStatus.BULL:
                if regime_res.is_valid and regime_res.status == BenchmarkRegimeStatus.DEFENSIVE:
                    self.log(f"Market Regime Check: Benchmark Close={regime_res.bm_close:.2f}, EMA20={regime_res.bm_ema20:.2f} -> DEFENSIVE")
                else:
                    self.log(f"Market Regime Check: [FAIL-CLOSED] Status={regime_res.status.value}, Error={regime_res.error_message} -> No new entries allowed.")
            else:
                self.log(f"Market Regime Check: Benchmark Close={regime_res.bm_close:.2f}, EMA20={regime_res.bm_ema20:.2f} -> BULL")

        conn = get_connection(read_only=True, reuse=True)

        all_syms = set(current_holdings.keys()) | set(screener_df["symbol"].dropna().tolist())
        prices = {}
        for sym in all_syms:
            query = "SELECT close FROM prices WHERE symbol = ? AND date = ?"
            df_price = pd.read_sql_query(query, conn, params=(sym, latest_date))
            if not df_price.empty:
                prices[sym] = float(df_price.iloc[0]["close"])
            else:
                prices[sym] = 0.0

        # Build deduplicated screener map: symbol -> best candidate row
        # If duplicates exist, keep highest volar score / best rank
        screener_map: Dict[str, pd.Series] = {}
        if not screener_df.empty:
            sorted_screener = screener_df.sort_values(
                by=["volar_score", "rank"] if "rank" in screener_df.columns else ["volar_score"],
                ascending=[False, True] if "rank" in screener_df.columns else [False]
            )
            for _, row in sorted_screener.iterrows():
                s = str(row["symbol"]).strip().upper()
                if s not in screener_map:
                    screener_map[s] = row

        # MTM Capital Basis Validation against open position equity
        holdings_mv = 0.0
        for sym, shares in current_holdings.items():
            if shares > 0:
                px = prices.get(sym, 0.0)
                if px <= 0 and sym in screener_map:
                    px = float(screener_map[sym].get("close", 0.0))
                holdings_mv += shares * px
        holdings_mv = round(holdings_mv, 2)

        # Fail closed on non-positive, non-finite, or stale capital below open position equity
        if capital is not None and capital < holdings_mv and not allow_research_overrides:
            raise ValueError(
                f"STALE_OR_INSUFFICIENT_CAPITAL: Supplied capital (₹{capital:,.2f}) is strictly less than "
                f"current holdings mark-to-market value (₹{holdings_mv:,.2f}). "
                f"Production capital basis must equal or exceed current open position equity."
            )

        # Authoritative NAV Derivation: NAV(T) = Cash(T) + sum_i (Shares_i * Close_i(T))
        if cash is not None:
            authoritative_nav = round(float(cash) + holdings_mv, 2)
            actual_cash = float(cash)
            if capital is None:
                capital = authoritative_nav
        else:
            if not allow_research_overrides:
                raise ValueError(
                    "AUTHORITATIVE_CASH_REQUIRED: Authoritative cash balance cannot be established. "
                    "Production execution requires authoritative cash via 'cash' or 'portfolio_state' (PortfolioState). "
                    "Cash cannot be inferred or manufactured from caller-supplied capital. "
                    "Research overrides require allow_research_overrides=True."
                )
            inferred_cash = max(0.0, round(capital - holdings_mv, 2))
            authoritative_nav = round(inferred_cash + holdings_mv, 2)
            actual_cash = inferred_cash

        if not allow_research_overrides:
            diff = round(capital - authoritative_nav, 2)
            if diff > 1e-2:
                raise ValueError(
                    f"INFLATED_CAPITAL_REJECTED: Supplied capital (₹{capital:,.2f}) exceeds authoritative MTM NAV (₹{authoritative_nav:,.2f}). "
                    f"Production risk budget cannot be inflated beyond NAV."
                )
            elif diff < -1e-2:
                raise ValueError(
                    f"STALE_OR_INSUFFICIENT_CAPITAL: Supplied capital (₹{capital:,.2f}) is strictly less than authoritative MTM NAV (₹{authoritative_nav:,.2f}). "
                    f"Production risk budget cannot be deflated below NAV."
                )

        effective_capital = capital if allow_research_overrides else authoritative_nav
        capital = effective_capital
        risk_budget = round(effective_capital * (risk_per_trade_pct / 100.0), 2)

        def _make_empty_orders_df() -> pd.DataFrame:
            empty_df = pd.DataFrame(columns=EMPTY_ORDERS_COLS)
            empty_df.attrs["authoritative_nav"] = authoritative_nav
            empty_df.attrs["capital_basis"] = effective_capital
            empty_df.attrs["risk_budget"] = risk_budget
            empty_df.attrs["holdings_mv"] = holdings_mv
            empty_df.attrs["cash"] = actual_cash
            empty_df.attrs["is_production_contract"] = not allow_research_overrides
            empty_df.attrs["research_overrides_active"] = allow_research_overrides
            empty_df.attrs["cash_authority"] = "AUTHORITATIVE_PORTFOLIO_STATE" if eff_state is not None else ("EXPLICIT_VERIFIED_CASH" if cash is not None else "SYNTHETIC_RESEARCH_OVERRIDE")
            self.last_authoritative_nav = authoritative_nav
            self.last_capital_basis = effective_capital
            self.last_risk_budget = risk_budget
            return empty_df

        self.log(f"Generating rebalance tickets: NAV=₹{authoritative_nav:,.0f} | Capital=₹{capital:,.0f} | Top N={top_n} | Exit Buffer Rank={exit_buffer_rank} | Sizing={sizing_mode} | AsOf={latest_date}")

        # 1. Evaluate Exits for existing holdings (Rank 40 Exit Buffer & Trend Rules)
        sell_orders = []
        retained_holdings = {}

        for sym, shares in current_holdings.items():
            if shares <= 0:
                continue

            sec_id = self.identity_mgr.resolve_security_id(sym, latest_date)
            s_row = screener_map.get(sym)
            close_price = prices.get(sym, 0.0)
            if close_price <= 0 and s_row is not None:
                close_price = float(s_row.get("close", 0.0))

            target_value = shares * close_price
            frictions = self.compute_frictions(target_value)
            raw_sec = s_row.get("sector", "OTHER") if s_row is not None else "OTHER"
            norm_sec = normalize_sector(raw_sec)

            exit_reason = None
            exit_reason_code = ScannerReasonCode.PASS.value
            exit_source_signal = "STOP_EXIT"

            if close_price <= 0:
                exit_reason = "DROPOUT_OR_DELISTED"
                exit_reason_code = ScannerReasonCode.DELISTED.value
                exit_source_signal = "DROPOUT_EXIT"
            elif s_row is not None:
                s_rank = s_row.get("rank", 999999)
                hi_252 = float(s_row.get("high_252", close_price))
                ema_200 = float(s_row.get("ema_200", close_price))
                if close_price < 0.80 * hi_252:
                    exit_reason = "STOP_52W_HIGH_RETRACEMENT"
                    exit_reason_code = ScannerReasonCode.BELOW_52W_HIGH_THRESHOLD.value
                    exit_source_signal = "STOP_EXIT"
                elif close_price < ema_200:
                    exit_reason = "STOP_200_EMA_BREAK"
                    exit_reason_code = ScannerReasonCode.BELOW_EMA200.value
                    exit_source_signal = "STOP_EXIT"
                elif s_rank > exit_buffer_rank:
                    exit_reason = f"DROPOUT_RANK_{s_rank}"
                    exit_reason_code = ScannerReasonCode.PORTFOLIO_BUFFER_EXCEEDED.value
                    exit_source_signal = "DROPOUT_EXIT"
            else:
                # Existing holding not present in screener output
                # Query historical prices from SQLite to check stops
                hist_query = """
                    SELECT high, close FROM prices
                    WHERE symbol = ? AND date <= ?
                    ORDER BY date DESC LIMIT 252
                """
                df_hist = pd.read_sql_query(hist_query, conn, params=(sym, latest_date))
                if not df_hist.empty:
                    hi_252 = float(df_hist["high"].max())
                    ema_200 = float(df_hist["close"].iloc[::-1].ewm(span=200, adjust=True).mean().iloc[-1]) if len(df_hist) >= 50 else close_price
                    if close_price < 0.80 * hi_252:
                        exit_reason = "STOP_52W_HIGH_RETRACEMENT"
                        exit_reason_code = ScannerReasonCode.BELOW_52W_HIGH_THRESHOLD.value
                        exit_source_signal = "STOP_EXIT"
                    elif close_price < ema_200:
                        exit_reason = "STOP_200_EMA_BREAK"
                        exit_reason_code = ScannerReasonCode.BELOW_EMA200.value
                        exit_source_signal = "STOP_EXIT"
                    else:
                        exit_reason = "DROPOUT_RANK_EXCEEDED"
                        exit_reason_code = ScannerReasonCode.PORTFOLIO_BUFFER_EXCEEDED.value
                        exit_source_signal = "DROPOUT_EXIT"
                else:
                    exit_reason = "DROPOUT_OR_DELISTED"
                    exit_reason_code = ScannerReasonCode.DELISTED.value
                    exit_source_signal = "DROPOUT_EXIT"

            if exit_reason is not None:
                sell_orders.append({
                    "action": "SELL",
                    "security_id": sec_id,
                    "symbol": sym,
                    "sector": norm_sec,
                    "close_price": close_price,
                    "atr_14": 0.0,
                    "stop_loss": 0.0,
                    "target_shares": 0,
                    "target_value": target_value,
                    "risk_allocated": 0.0,
                    "stt": frictions["stt"],
                    "exchange_turnover": frictions["exchange_turnover"],
                    "brokerage": frictions["brokerage"],
                    "gst": frictions["gst"],
                    "stamp_duty": frictions["stamp_duty"],
                    "total_friction": frictions["total_friction"],
                    "total_cost": target_value - frictions["total_friction"],
                    "reason": exit_reason,
                    "reason_code": exit_reason_code,
                    "as_of_date": latest_date,
                    "source_signal": exit_source_signal,
                })
            else:
                retained_holdings[sym] = shares

        # 2. Select New Entrants for Open Slots
        open_slots = max(0, top_n - len(retained_holdings))
        candidates_to_add = []
        sector_counts: Dict[str, int] = {}
        seen_symbols: Set[str] = set()
        seen_security_ids: Set[str] = set()

        for sym in retained_holdings:
            s_row = screener_map.get(sym)
            raw_sec = s_row.get("sector", "OTHER") if s_row is not None else "OTHER"
            sec = normalize_sector(raw_sec)
            sector_counts[sec] = sector_counts.get(sec, 0) + 1
            sec_id = self.identity_mgr.resolve_security_id(sym, latest_date)
            seen_symbols.add(sym)
            seen_security_ids.add(sec_id)

        if open_slots > 0 and is_bull:
            # Deterministic ordering: volar_score DESC, ret_1y DESC, symbol ASC
            cand_candidates = screener_df.copy()
            sort_cols = ["volar_score"]
            sort_asc = [False]
            if "ret_1y" in cand_candidates.columns:
                sort_cols.append("ret_1y")
                sort_asc.append(False)
            if "rank" in cand_candidates.columns:
                sort_cols.append("rank")
                sort_asc.append(True)
            sort_cols.append("symbol")
            sort_asc.append(True)

            cand_candidates = cand_candidates.sort_values(by=sort_cols, ascending=sort_asc).reset_index(drop=True)

            for _, row in cand_candidates.iterrows():
                sym = str(row["symbol"]).strip().upper()
                sec_id = self.identity_mgr.resolve_security_id(sym, latest_date)
                if sec_id == f"SEC_{sym}" and row.get("security_id"):
                    sec_id = str(row["security_id"]).strip()

                # Canonical identity deduplication (both by symbol and canonical security_id)
                if sym in seen_symbols or sec_id in seen_security_ids:
                    continue

                # Downstream Actionable BUY Firewall Verification
                is_safe, rej_msg, r_code = validate_candidate_safety(row, top_n=top_n)
                if not is_safe:
                    self.log(f"Candidate {sym} rejected by downstream safety firewall: {rej_msg}")
                    continue

                sec = normalize_sector(row.get("sector"))
                if sector_counts.get(sec, 0) < max_per_sector:
                    candidates_to_add.append(row)
                    sector_counts[sec] = sector_counts.get(sec, 0) + 1
                    seen_symbols.add(sym)
                    seen_security_ids.add(sec_id)

                if len(candidates_to_add) >= open_slots:
                    break
        elif not is_bull:
            self.log("Defensive regime active: Benchmark < 20 EMA or Invalid. Pausing new entries, holding cash.")

        target_candidates = []
        for sym in retained_holdings:
            if sym in screener_map:
                target_candidates.append(screener_map[sym])
            else:
                target_candidates.append(pd.Series({
                    "symbol": sym,
                    "sector": "OTHER",
                    "close": prices.get(sym, 0.0),
                    "security_id": self.identity_mgr.resolve_security_id(sym, latest_date),
                }))
        for row in candidates_to_add:
            target_candidates.append(row)

        target_df = pd.DataFrame(target_candidates)
        if target_df.empty and not sell_orders:
            self.log("No qualifying screener candidates found.")
            return _make_empty_orders_df()

        atr_map = self.compute_atr_14(target_df["symbol"].tolist(), latest_date) if not target_df.empty else {}
        per_stock_equal = capital / max(top_n, 1) if not target_df.empty else 0.0
        risk_budget = capital * (risk_per_trade_pct / 100.0)

        # 3. Process Target Shares and Orders
        buy_hold_orders = []
        for _, row in target_df.iterrows():
            sym = str(row["symbol"]).strip().upper()
            sec_id = self.identity_mgr.resolve_security_id(sym, latest_date)
            if sec_id == f"SEC_{sym}" and row.get("security_id"):
                sec_id = str(row["security_id"]).strip()
            sector = normalize_sector(row.get("sector"))
            close_price = prices.get(sym) or float(row.get("close", 0.0))
            if not close_price or close_price <= 0 or not math.isfinite(close_price):
                continue

            atr = atr_map.get(sym, close_price * 0.03)
            if not math.isfinite(atr) or atr <= 0:
                atr = round(close_price * 0.03, 2)
            stop_loss = round(max(0.01, close_price - 2.0 * atr), 2)

            if sizing_mode == "atr_risk_parity" and atr > 0:
                risk_per_share = max(2.0 * atr, close_price * 0.02)
                q_risk = int(risk_budget // risk_per_share)
                q_cap = int((capital * 0.25) // close_price)
                target_shares = max(0, min(q_risk, q_cap))
            else:
                target_shares = math.floor(per_stock_equal / close_price)

            current_shares = current_holdings.get(sym, 0)
            action = "HOLD" if current_shares > 0 else "BUY"

            # Avoid 0-share buy tickets
            if action == "BUY" and target_shares <= 0:
                continue

            target_value = target_shares * close_price
            frictions = self.compute_frictions(target_value)

            reason_desc = "BUFFER_RETAINED" if action == "HOLD" else "MOMENTUM_ENTRY"
            reason_code = ScannerReasonCode.PORTFOLIO_BUFFER_RETAINED.value if action == "HOLD" else ScannerReasonCode.PASS.value
            source_sig = "BUFFER_RETAIN" if action == "HOLD" else "SCANNER"

            buy_hold_orders.append({
                "action": action,
                "security_id": sec_id,
                "symbol": sym,
                "sector": sector,
                "close_price": close_price,
                "atr_14": atr,
                "stop_loss": stop_loss,
                "target_shares": target_shares,
                "target_value": target_value,
                "risk_allocated": round(target_shares * (close_price - stop_loss), 2),
                "stt": frictions["stt"],
                "exchange_turnover": frictions["exchange_turnover"],
                "brokerage": frictions["brokerage"],
                "gst": frictions["gst"],
                "stamp_duty": frictions["stamp_duty"],
                "total_friction": frictions["total_friction"],
                "total_cost": target_value + frictions["total_friction"],
                "reason": reason_desc,
                "reason_code": reason_code,
                "as_of_date": latest_date,
                "source_signal": source_sig,
            })

        # Budget normalization: ensure BUY orders do not exceed remaining unallocated capital
        held_value = sum(o["target_value"] for o in buy_hold_orders if o["action"] == "HOLD")
        avail_for_buys = max(0.0, (capital * 0.99) - held_value)
        buy_orders = [o for o in buy_hold_orders if o["action"] == "BUY"]
        buy_requested = sum(o["total_cost"] for o in buy_orders)

        if buy_requested > avail_for_buys and buy_requested > 0:
            scale_factor = avail_for_buys / buy_requested
            for o in buy_orders:
                scaled_shares = int(o["target_shares"] * scale_factor)
                o["target_shares"] = scaled_shares
                o["target_value"] = scaled_shares * o["close_price"]
                o["risk_allocated"] = round(scaled_shares * (o["close_price"] - o["stop_loss"]), 2)
                frictions = self.compute_frictions(o["target_value"])
                o["stt"] = frictions["stt"]
                o["exchange_turnover"] = frictions["exchange_turnover"]
                o["brokerage"] = frictions["brokerage"]
                o["gst"] = frictions["gst"]
                o["stamp_duty"] = frictions["stamp_duty"]
                o["total_friction"] = frictions["total_friction"]
                o["total_cost"] = o["target_value"] + frictions["total_friction"]

        orders = buy_hold_orders + sell_orders
        if not orders:
            return _make_empty_orders_df()
        orders_df = pd.DataFrame(orders)

        if not orders_df.empty:
            summary_row = pd.DataFrame([{
                'action': 'SUMMARY',
                'security_id': 'TOTAL',
                'symbol': 'TOTAL',
                'sector': f'{len(target_candidates)} Positions ({len(sector_counts)} Sectors)',
                'close_price': 0.0,
                'atr_14': 0.0,
                'stop_loss': 0.0,
                'target_shares': orders_df['target_shares'].sum(),
                'target_value': orders_df['target_value'].sum(),
                'risk_allocated': orders_df['risk_allocated'].sum(),
                'stt': orders_df['stt'].sum(),
                'exchange_turnover': orders_df['exchange_turnover'].sum(),
                'brokerage': orders_df['brokerage'].sum(),
                'gst': orders_df['gst'].sum(),
                'stamp_duty': orders_df['stamp_duty'].sum(),
                'total_friction': orders_df['total_friction'].sum(),
                'total_cost': orders_df['total_cost'].sum(),
                'reason': 'PORTFOLIO_REBALANCE_TOTAL',
                'reason_code': 'PORTFOLIO_SUMMARY',
                'as_of_date': latest_date,
                'source_signal': 'SYSTEM',
            }])
            orders_df = pd.concat([orders_df, summary_row], ignore_index=True)

        self.last_authoritative_nav = authoritative_nav
        self.last_capital_basis = effective_capital
        self.last_risk_budget = risk_budget
        orders_df.attrs["authoritative_nav"] = authoritative_nav
        orders_df.attrs["capital_basis"] = effective_capital
        orders_df.attrs["risk_budget"] = risk_budget
        orders_df.attrs["holdings_mv"] = holdings_mv
        orders_df.attrs["cash"] = actual_cash
        orders_df.attrs["is_production_contract"] = not allow_research_overrides
        orders_df.attrs["research_overrides_active"] = allow_research_overrides
        orders_df.attrs["cash_authority"] = "AUTHORITATIVE_PORTFOLIO_STATE" if eff_state is not None else ("EXPLICIT_VERIFIED_CASH" if cash is not None else "SYNTHETIC_RESEARCH_OVERRIDE")

        return orders_df

    def export_orders(self, orders_df: pd.DataFrame) -> Path:
        """Saves orders DataFrame to a CSV and a human-readable text file."""
        csv_path = self.reports_dir / "rebalance_orders.csv"
        txt_path = self.reports_dir / "rebalance_orders.txt"

        orders_df.to_csv(csv_path, index=False)
        self.log(f"Exported orders to CSV: {csv_path}")

        with open(txt_path, 'w', encoding="utf-8") as f:
            f.write("=== REBALANCE ORDERS LEDGER (MIP-1 ATR RISK PARITY) ===\n")
            f.write(f"Generated at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            if not orders_df.empty:
                summary_df = orders_df[orders_df['action'] == 'SUMMARY']
                details_df = orders_df[orders_df['action'] != 'SUMMARY']

                f.write(details_df.to_string(index=False))
                f.write("\n\n=== SUMMARY ===\n")
                f.write(summary_df.to_string(index=False))
            else:
                f.write("No orders generated.\n")

        self.log(f"Exported orders to TXT: {txt_path}")
        return csv_path
