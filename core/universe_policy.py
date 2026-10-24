"""Universe policy for historical research.

Rules enforced here (single source of truth):

* ``ALL`` is the only implicit historical universe. It is the full database
  cross-section and includes delisted names, so it is not conditioned on
  today's index membership.
* A named index (NIFTY500, NIFTY750, ...) is resolved from its point-in-time
  table when one exists (NIFTY500: 50 snapshots, 2016-01-18 onward). An index
  without a PIT table (e.g. NIFTY750) is **refused** unless the caller supplies
  an explicit symbol list: a current-list fallback would be survivorship/
  look-ahead biased. The live scanner is the only component allowed to use the
  latest constituents.
* A cross-sectional run is refused when the eligible universe (symbols with
  the 252-bar history the strategy needs) is below ``MIN_ELIGIBLE_SYMBOLS``.
  This rejects under-covered windows such as 2008 and 2011 instead of
  publishing a number that looks like a backtest.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence

MIN_ELIGIBLE_SYMBOLS = 100

_FULL_CROSS_SECTION_ALIASES = {"", "ALL", "MASTER", "PIT"}


class UniversePolicyError(ValueError):
    """Raised when a requested universe would be biased or too thin."""


def all_db_symbols(base_dir: Optional[Path] = None) -> List[str]:
    """Every symbol in the price store, including delisted names."""
    from core.data_engine import get_db_path

    db_path = Path(base_dir) / "data" / "universe.db" if base_dir else get_db_path()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return sorted({r[0] for r in con.execute("SELECT DISTINCT symbol FROM prices")})
    finally:
        con.close()


def resolve_universe(
    universe_mode: Optional[str],
    start_date: str,
    base_dir: Optional[Path] = None,
    explicit_symbols: Optional[Sequence[str]] = None,
    allow_current_constituents: bool = False,
    end_date: Optional[str] = None,
) -> Dict[str, object]:
    """Resolve a research universe without falling back to current constituents.

    Returns a dict with:
      label, symbols (None means no filter / full cross-section), source,
      survivorship_bias_risk, data_completeness_risk
    """
    if explicit_symbols is not None:
        symbols = sorted({str(s).strip().upper() for s in explicit_symbols if str(s).strip()})
        if not symbols:
            raise UniversePolicyError("EMPTY_EXPLICIT_UNIVERSE: explicit symbol list is empty.")
        return {
            "label": str(universe_mode or "EXPLICIT").strip().upper(),
            "symbols": symbols,
            "source": "EXPLICIT_SYMBOLS",
            "survivorship_bias_risk": False,
            "data_completeness_risk": False,
            "pit_index": None,
        }

    label = str(universe_mode or "ALL").strip().upper()
    if label in _FULL_CROSS_SECTION_ALIASES:
        return {
            "label": "ALL",
            "symbols": None,
            "source": "FULL_CROSS_SECTION",
            "survivorship_bias_risk": False,
            # The DB includes delisted names but is not a certified historical
            # security master; this residual risk is disclosed, not hidden.
            "data_completeness_risk": True,
            "pit_index": None,
        }

    # Point-in-time membership: use the actual constituents on each date.
    from core.pit_membership import has_coverage, union_members_db

    if has_coverage(label, start_date, end_date=end_date, base_dir=base_dir):
        end = end_date or start_date
        symbols = union_members_db(label, start_date, end, base_dir)
        if not symbols:
            raise UniversePolicyError(
                f"EMPTY_POINT_IN_TIME_UNIVERSE: no DB symbols map to '{label}' between "
                f"{start_date} and {end}."
            )
        return {
            "label": label,
            "symbols": symbols,
            "source": "PIT_SNAPSHOT",
            "survivorship_bias_risk": False,
            "data_completeness_risk": True,
            "pit_index": label,
        }

    if allow_current_constituents:
        # Explicit test-only fixture path. Production entry points never pass
        # this flag; the resulting cube is marked survivorship-biased.
        from core.data_engine import load_universe_constituents

        current = sorted(load_universe_constituents(label))
        if not current:
            raise UniversePolicyError(f"UNRESOLVED_UNIVERSE: '{label}' has no current constituents.")
        return {
            "label": label,
            "symbols": current,
            "source": "CURRENT_CONSTITUENTS_TEST_ONLY",
            "survivorship_bias_risk": True,
            "data_completeness_risk": True,
            "pit_index": None,
        }

    raise UniversePolicyError(
        f"INDEX_UNIVERSE_REQUIRES_POINT_IN_TIME: '{label}' historical research is disabled. "
        f"No point-in-time constituent snapshot exists on/before {start_date}, and falling back to "
        f"today's constituents would be survivorship/look-ahead biased. Use universe_mode='ALL' "
        f"for the full delisted-inclusive cross-section, or pass an explicit symbol list for a "
        f"deliberate research universe. The live scanner still uses the latest constituents."
    )


def eligible_symbol_count(
    symbol_bar_counts: Dict[str, int], min_bars: int = 252
) -> int:
    return int(sum(1 for c in symbol_bar_counts.values() if int(c) >= int(min_bars)))


def min_pit_eligible(member_count: int) -> int:
    """Scale the PIT breadth floor to the index size (Nifty 50 needs fewer)."""
    return min(MIN_ELIGIBLE_SYMBOLS, max(10, int(member_count) // 2))


def check_breadth(
    eligible_symbols: int,
    universe_source: str,
    min_symbols: int = MIN_ELIGIBLE_SYMBOLS,
) -> None:
    """Refuse a cross-sectional run on a thin universe.

    Explicit-symbol universes are deliberate research fixtures, so the gate is
    applied only to the implicit FULL_CROSS_SECTION universe.
    """
    if universe_source != "FULL_CROSS_SECTION":
        return
    if int(eligible_symbols) < int(min_symbols):
        raise UniversePolicyError(
            f"INSUFFICIENT_UNIVERSE_BREADTH: {eligible_symbols} symbols have the required 252-bar "
            f"history; minimum is {min_symbols}. Refusing to run a cross-sectional strategy on an "
            f"under-covered window (e.g. 2008/2011)."
        )
