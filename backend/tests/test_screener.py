"""Tests for the multi-asset screener — universe, compute, service.

Compute tests build `ScreenerRow` lists by hand. Service tests patch
`_build_universe_blocking` to keep yfinance off the wire (mirrors the
sector-rotation test pattern).
"""
from __future__ import annotations

from collections import Counter
from unittest.mock import patch

import pytest

from app.services import screener_service
from core.screener import (
    SCREENER_UNIVERSE,
    ScreenerFilter,
    ScreenerRow,
    apply_filter,
    sort_and_paginate,
)


# ----- Universe -----


def test_universe_has_55_distinct_symbols():
    symbols = [e.symbol for e in SCREENER_UNIVERSE]
    assert len(symbols) == 55
    assert len(set(symbols)) == 55


def test_universe_covers_all_eleven_sectors():
    """Exactly the 11 GICS sectors with 5 entries each."""
    sectors_count = Counter(e.sector for e in SCREENER_UNIVERSE)
    expected = {
        "Technology",
        "Financials",
        "Health Care",
        "Consumer Discretionary",
        "Consumer Staples",
        "Energy",
        "Industrials",
        "Materials",
        "Utilities",
        "Real Estate",
        "Communication Services",
    }
    assert set(sectors_count.keys()) == expected
    for sector, count in sectors_count.items():
        assert count == 5, f"{sector} has {count} entries, expected 5"


# ----- Filter -----


def _row(
    symbol: str,
    sector: str = "Technology",
    *,
    market_cap: float | None = None,
    pe_ratio: float | None = None,
    peg_ratio: float | None = None,
    revenue_growth: float | None = None,
    momentum_3m: float | None = None,
    latest_close: float | None = None,
) -> ScreenerRow:
    return ScreenerRow(
        symbol=symbol,
        sector=sector,
        market_cap=market_cap,
        pe_ratio=pe_ratio,
        peg_ratio=peg_ratio,
        revenue_growth=revenue_growth,
        momentum_3m=momentum_3m,
        latest_close=latest_close,
    )


def test_filter_no_bounds_returns_all():
    rows = [_row("AAPL"), _row("MSFT"), _row("NVDA")]
    out = apply_filter(rows, ScreenerFilter())
    assert [r.symbol for r in out] == ["AAPL", "MSFT", "NVDA"]


def test_filter_sector_exact_match_case_insensitive():
    rows = [
        _row("AAPL", sector="Technology"),
        _row("JPM", sector="Financials"),
        _row("NVDA", sector="Technology"),
    ]
    out = apply_filter(rows, ScreenerFilter(sector="technology"))
    assert {r.symbol for r in out} == {"AAPL", "NVDA"}

    out_caps = apply_filter(rows, ScreenerFilter(sector="TECHNOLOGY"))
    assert {r.symbol for r in out_caps} == {"AAPL", "NVDA"}


def test_filter_excludes_rows_with_none_when_bound_set():
    """A row with pe_ratio=None must be dropped when min_pe is set."""
    rows = [
        _row("AAPL", pe_ratio=20.0),
        _row("MSFT", pe_ratio=None),
        _row("NVDA", pe_ratio=40.0),
    ]
    out = apply_filter(rows, ScreenerFilter(min_pe=10.0))
    assert {r.symbol for r in out} == {"AAPL", "NVDA"}


def test_filter_min_max_inclusive():
    """Bounds are inclusive at the boundary on both sides."""
    rows = [
        _row("A", market_cap=1e9),
        _row("B", market_cap=5e9),
        _row("C", market_cap=10e9),
        _row("D", market_cap=11e9),
    ]
    out = apply_filter(rows, ScreenerFilter(min_market_cap=1e9, max_market_cap=10e9))
    assert {r.symbol for r in out} == {"A", "B", "C"}


# ----- Sort & paginate -----


def test_sort_by_market_cap_descending_with_none_at_end():
    rows = [
        _row("A", market_cap=1e9),
        _row("B", market_cap=5e9),
        _row("C", market_cap=None),
        _row("D", market_cap=10e9),
    ]
    out, total = sort_and_paginate(rows, sort_by="market_cap", descending=True, page=1, page_size=10)
    assert total == 4
    assert [r.symbol for r in out] == ["D", "B", "A", "C"]


def test_sort_by_market_cap_ascending_with_none_still_at_end():
    """None must sort last regardless of direction."""
    rows = [
        _row("A", market_cap=1e9),
        _row("B", market_cap=5e9),
        _row("C", market_cap=None),
        _row("D", market_cap=10e9),
    ]
    out, total = sort_and_paginate(rows, sort_by="market_cap", descending=False, page=1, page_size=10)
    assert total == 4
    assert [r.symbol for r in out] == ["A", "B", "D", "C"]


def test_sort_stable_ties_break_on_symbol():
    """Equal market caps → tied rows ordered by symbol ascending in both directions."""
    rows = [
        _row("MSFT", market_cap=5e9),
        _row("AAPL", market_cap=5e9),
        _row("NVDA", market_cap=5e9),
    ]
    out_desc, _ = sort_and_paginate(rows, sort_by="market_cap", descending=True, page=1, page_size=10)
    assert [r.symbol for r in out_desc] == ["AAPL", "MSFT", "NVDA"]

    out_asc, _ = sort_and_paginate(rows, sort_by="market_cap", descending=False, page=1, page_size=10)
    assert [r.symbol for r in out_asc] == ["AAPL", "MSFT", "NVDA"]


def test_paginate_basic_first_page():
    rows = [_row(f"S{i:02d}", market_cap=float(i)) for i in range(25)]
    out, total = sort_and_paginate(rows, sort_by="market_cap", descending=True, page=1, page_size=10)
    assert total == 25
    assert len(out) == 10
    # Top 10 by market cap descending → S24..S15.
    assert [r.symbol for r in out] == [f"S{i:02d}" for i in range(24, 14, -1)]


def test_paginate_out_of_range_returns_empty_with_correct_total():
    rows = [_row(f"S{i:02d}", market_cap=float(i)) for i in range(10)]
    out, total = sort_and_paginate(rows, sort_by="market_cap", descending=True, page=99, page_size=10)
    assert out == []
    assert total == 10


def test_unknown_sort_by_raises_value_error():
    rows = [_row("AAPL")]
    with pytest.raises(ValueError):
        sort_and_paginate(rows, sort_by="not_a_column")


# ----- Service -----


def _fake_payload(symbols: list[str]) -> dict:
    """Mimic _build_universe_blocking's return shape."""
    from datetime import datetime, timezone

    rows = [
        ScreenerRow(
            symbol=s,
            sector="Technology",
            market_cap=1e9 + idx,
            pe_ratio=20.0 + idx,
            peg_ratio=1.5,
            revenue_growth=0.10,
            momentum_3m=0.05,
            latest_close=100.0 + idx,
        )
        for idx, s in enumerate(symbols)
    ]
    return {"rows": rows, "as_of": datetime.now(timezone.utc)}


@pytest.mark.asyncio
async def test_service_uses_cache():
    """Two calls within TTL → fetcher invoked once."""
    screener_service._cache = None  # noqa: SLF001
    call_count = {"n": 0}

    def fake_build(symbols):
        call_count["n"] += 1
        return _fake_payload(symbols)

    with patch.object(
        screener_service,
        "_build_universe_blocking",
        side_effect=fake_build,
    ):
        first = await screener_service.search(
            spec=ScreenerFilter(),
            sort_by="market_cap",
            descending=True,
            page=1,
            page_size=20,
        )
        second = await screener_service.search(
            spec=ScreenerFilter(),
            sort_by="market_cap",
            descending=True,
            page=1,
            page_size=20,
        )

    assert call_count["n"] == 1
    assert first["total"] == 55
    assert second["total"] == 55


@pytest.mark.asyncio
async def test_service_force_refresh_bypasses_cache():
    screener_service._cache = None  # noqa: SLF001
    call_count = {"n": 0}

    def fake_build(symbols):
        call_count["n"] += 1
        return _fake_payload(symbols)

    with patch.object(
        screener_service,
        "_build_universe_blocking",
        side_effect=fake_build,
    ):
        await screener_service.search(
            spec=ScreenerFilter(),
            sort_by="market_cap",
            descending=True,
            page=1,
            page_size=20,
        )
        await screener_service.search(
            spec=ScreenerFilter(),
            sort_by="market_cap",
            descending=True,
            page=1,
            page_size=20,
            force=True,
        )

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_service_handles_empty_fetch():
    """Fetcher returns an empty rows list → response gives rows=[], total=0."""
    screener_service._cache = None  # noqa: SLF001
    from datetime import datetime, timezone

    with patch.object(
        screener_service,
        "_build_universe_blocking",
        return_value={"rows": [], "as_of": datetime.now(timezone.utc)},
    ):
        payload = await screener_service.search(
            spec=ScreenerFilter(),
            sort_by="market_cap",
            descending=True,
            page=1,
            page_size=20,
        )

    assert payload["rows"] == []
    assert payload["total"] == 0
    assert payload["page"] == 1
    assert payload["page_size"] == 20
