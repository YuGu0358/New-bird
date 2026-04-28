"""Screener compute — pure filter / sort / paginate. No I/O.

The service layer enriches the universe via yfinance, then hands the row
list to these helpers. Keeping the business rules pure means tests build
rows by hand and the logic is reusable for any future enriched dataset.

Conventions
-----------
- A `None` bound on `ScreenerFilter` means "no constraint".
- A row with `None` for a filtered metric is **excluded** (we can't prove
  a missing value satisfies the bound, and ranking screens don't want
  rows with empty cells creeping past the filter).
- Sort: `None` values always sort last regardless of direction. Keeping
  empty cells at the bottom matches user intuition for ranking views.
- Sort is stable; ties break on `symbol` ascending.
"""
from __future__ import annotations

from dataclasses import dataclass


# Columns that `sort_by` accepts. Anything else → ValueError. Kept as a
# frozenset so callers can introspect (the API uses this for validation).
SORTABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "symbol",
        "sector",
        "market_cap",
        "pe_ratio",
        "peg_ratio",
        "revenue_growth",
        "momentum_3m",
        "latest_close",
    }
)


@dataclass
class ScreenerRow:
    symbol: str
    sector: str
    market_cap: float | None = None
    pe_ratio: float | None = None  # trailing P/E
    peg_ratio: float | None = None
    revenue_growth: float | None = None  # YoY revenue growth, fraction (0.12 = 12%)
    momentum_3m: float | None = None  # 3-month price return, fraction
    latest_close: float | None = None


@dataclass(frozen=True)
class ScreenerFilter:
    sector: str | None = None  # exact match against ScreenerRow.sector (case-insensitive)
    min_market_cap: float | None = None
    max_market_cap: float | None = None
    min_pe: float | None = None
    max_pe: float | None = None
    min_peg: float | None = None
    max_peg: float | None = None
    min_revenue_growth: float | None = None
    max_revenue_growth: float | None = None
    min_momentum_3m: float | None = None
    max_momentum_3m: float | None = None


# (filter-attr-name on lo, filter-attr-name on hi, ScreenerRow attr).
# Drives apply_filter so adding a numeric filter is one line.
_NUMERIC_BOUNDS: tuple[tuple[str, str, str], ...] = (
    ("min_market_cap", "max_market_cap", "market_cap"),
    ("min_pe", "max_pe", "pe_ratio"),
    ("min_peg", "max_peg", "peg_ratio"),
    ("min_revenue_growth", "max_revenue_growth", "revenue_growth"),
    ("min_momentum_3m", "max_momentum_3m", "momentum_3m"),
)


def apply_filter(
    rows: list[ScreenerRow], spec: ScreenerFilter
) -> list[ScreenerRow]:
    """Keep rows that satisfy every populated bound in `spec`.

    A `None` row value for a column with a populated bound disqualifies
    the row for that column. Sector match is case-insensitive exact.
    """
    target_sector = spec.sector.strip().lower() if spec.sector else None

    out: list[ScreenerRow] = []
    for row in rows:
        if target_sector is not None:
            if (row.sector or "").strip().lower() != target_sector:
                continue

        keep = True
        for lo_attr, hi_attr, row_attr in _NUMERIC_BOUNDS:
            lo = getattr(spec, lo_attr)
            hi = getattr(spec, hi_attr)
            if lo is None and hi is None:
                continue
            value = getattr(row, row_attr)
            if value is None:
                # Bound set but value missing → exclude (strict).
                keep = False
                break
            if lo is not None and value < lo:
                keep = False
                break
            if hi is not None and value > hi:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def sort_and_paginate(
    rows: list[ScreenerRow],
    *,
    sort_by: str = "market_cap",
    descending: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[ScreenerRow], int]:
    """Sort, paginate, return (page_rows, total_after_filter).

    `None` values always sort last regardless of direction. Sort is stable
    with `symbol` ascending as the tiebreaker. `page` is 1-indexed;
    `page_size` clamps to [1, 100]. Out-of-range pages return [] with the
    correct total.

    Raises ValueError on unknown `sort_by`.
    """
    if sort_by not in SORTABLE_COLUMNS:
        raise ValueError(
            f"unknown sort_by {sort_by!r}; expected one of "
            f"{sorted(SORTABLE_COLUMNS)}"
        )

    total = len(rows)
    if total == 0:
        return [], 0

    # Two-stage sort:
    # 1. Stable sort by symbol ascending (the ultimate tiebreaker).
    # 2. Stable sort by (none_flag, value) — for descending we negate
    #    numeric values or reverse string comparisons via `reverse=True`
    #    on the *present* slice, but we must keep None rows at the bottom.
    # Easier path: split into present/missing, sort each, concatenate.
    present: list[ScreenerRow] = []
    missing: list[ScreenerRow] = []
    for r in rows:
        if getattr(r, sort_by) is None:
            missing.append(r)
        else:
            present.append(r)

    # Sort present rows by (value, symbol). For descending we sort by value
    # descending then by symbol ascending — Python's sort is stable, so we
    # do symbol-asc first, then value sort.
    present.sort(key=lambda r: r.symbol)
    present.sort(key=lambda r: getattr(r, sort_by), reverse=descending)

    # Missing rows always at the end, ordered by symbol ascending.
    missing.sort(key=lambda r: r.symbol)

    sorted_rows = present + missing

    # Paginate.
    page_size_clamped = max(1, min(int(page_size), 100))
    page_idx = max(1, int(page))
    start = (page_idx - 1) * page_size_clamped
    end = start + page_size_clamped
    if start >= total:
        return [], total
    return sorted_rows[start:end], total
