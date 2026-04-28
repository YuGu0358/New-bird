"""Tests for sector rotation compute + service.

Pure-compute tests build hand-built series and verify return windows / rank
ordering / rank-change. The service test patches yfinance via the module
boundary so we don't hit the network.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from core.sector_rotation import (
    RETURN_WINDOWS,
    SECTOR_ETFS,
    compute_returns,
    compute_rotation,
)
from app.services import sector_rotation_service


def _ramp(*, start: date, days: int, base: float, daily_pct: float) -> list[tuple[date, float]]:
    """Build a list of (date, close) where each close grows by daily_pct."""
    bars: list[tuple[date, float]] = []
    price = base
    d = start
    for _ in range(days):
        bars.append((d, price))
        price *= 1.0 + daily_pct
        d = d + timedelta(days=1)
    return bars


def test_compute_returns_empty_series():
    out, latest_d, latest_c = compute_returns([])
    assert latest_d is None
    assert latest_c is None
    for label, _ in RETURN_WINDOWS:
        assert out[label] is None


def test_compute_returns_one_day_unable_to_compute():
    """A single bar can't anchor 1d/5d/1m/3m. YTD anchors on itself → 0%."""
    bars = [(date(2026, 4, 28), 100.0)]
    out, latest_d, latest_c = compute_returns(bars)
    assert latest_d == date(2026, 4, 28)
    assert latest_c == 100.0
    assert out["1d"] is None
    assert out["5d"] is None
    assert out["1m"] is None
    assert out["3m"] is None
    assert out["ytd"] == 0.0


def test_compute_returns_simple_ramp():
    """100 trading days of +1%/day. 1d return ≈ 0.01, 5d ≈ 1.01^5-1, etc."""
    bars = _ramp(start=date(2026, 1, 2), days=70, base=100.0, daily_pct=0.01)
    out, _, _ = compute_returns(bars)
    assert out["1d"] == pytest.approx(0.01, rel=1e-6)
    assert out["5d"] == pytest.approx(1.01**5 - 1, rel=1e-6)
    assert out["1m"] == pytest.approx(1.01**21 - 1, rel=1e-6)
    assert out["3m"] == pytest.approx(1.01**63 - 1, rel=1e-6)
    # YTD anchors at first bar (Jan 2) which is start of year
    assert out["ytd"] == pytest.approx(1.01**69 - 1, rel=1e-6)


def test_compute_returns_skips_when_window_exceeds_history():
    """Only 10 days of data → 1m / 3m / ytd should be None for cross-year anchor."""
    bars = _ramp(start=date(2026, 4, 1), days=10, base=100.0, daily_pct=0.01)
    out, _, _ = compute_returns(bars)
    assert out["1d"] is not None
    assert out["5d"] is not None
    assert out["1m"] is None
    assert out["3m"] is None
    # YTD: anchor is first bar inside 2026 (= Apr 1), latest is Apr 10 → return defined
    assert out["ytd"] is not None


def test_compute_returns_ytd_uses_first_bar_in_latest_year():
    """Bars span Dec 2025 → Apr 2026; YTD anchors on first 2026 bar."""
    bars = [
        (date(2025, 12, 28), 90.0),
        (date(2025, 12, 29), 95.0),
        (date(2026, 1, 2), 100.0),  # YTD anchor
        (date(2026, 1, 3), 102.0),
        (date(2026, 4, 28), 110.0),  # latest
    ]
    out, _, _ = compute_returns(bars)
    assert out["ytd"] == pytest.approx((110.0 / 100.0) - 1.0, rel=1e-6)


def test_compute_rotation_assigns_ranks_and_change():
    """Two symbols with different perf → ranks 1/2 in each window."""
    series = {
        "XLK": _ramp(start=date(2026, 1, 2), days=70, base=100.0, daily_pct=0.01),
        "XLU": _ramp(start=date(2026, 1, 2), days=70, base=100.0, daily_pct=-0.005),
    }
    snap = compute_rotation(
        series_by_symbol=series,
        sectors=[("XLK", "Technology"), ("XLU", "Utilities")],
    )
    by_symbol = {r.symbol: r for r in snap.rows}
    assert by_symbol["XLK"].ranks["1d"] == 1
    assert by_symbol["XLU"].ranks["1d"] == 2
    assert by_symbol["XLK"].ranks["1m"] == 1
    # 5d rank == 1m rank for XLK → change is 0
    assert by_symbol["XLK"].rank_change_5d_vs_1m == 0
    assert by_symbol["XLU"].rank_change_5d_vs_1m == 0


def test_compute_rotation_missing_symbol_yields_all_none():
    """A symbol with no series in the input still gets a row with None values."""
    snap = compute_rotation(
        series_by_symbol={},
        sectors=[("XLK", "Technology")],
    )
    assert len(snap.rows) == 1
    row = snap.rows[0]
    assert row.symbol == "XLK"
    assert row.latest_close is None
    assert all(v is None for v in row.returns.values())
    assert all(v is None for v in row.ranks.values())
    assert row.rank_change_5d_vs_1m is None
    assert snap.as_of is None


def test_compute_rotation_excludes_none_returns_from_rank():
    """A symbol whose 1m return is None must not occupy a rank slot."""
    long_series = _ramp(start=date(2026, 1, 2), days=40, base=100.0, daily_pct=0.005)
    short_series = _ramp(start=date(2026, 4, 1), days=10, base=100.0, daily_pct=0.01)
    snap = compute_rotation(
        series_by_symbol={"XLK": long_series, "XLF": short_series},
        sectors=[("XLK", "Technology"), ("XLF", "Financials")],
    )
    by_symbol = {r.symbol: r for r in snap.rows}
    # XLF has only 10 bars, so 1m return is None → rank should be None
    assert by_symbol["XLF"].returns["1m"] is None
    assert by_symbol["XLF"].ranks["1m"] is None
    # XLK is the only candidate → rank 1
    assert by_symbol["XLK"].ranks["1m"] == 1


def test_compute_rotation_as_of_picks_latest_across_symbols():
    series = {
        "XLK": [(date(2026, 4, 27), 100.0), (date(2026, 4, 28), 101.0)],
        "XLU": [(date(2026, 4, 26), 50.0), (date(2026, 4, 27), 50.5)],
    }
    snap = compute_rotation(
        series_by_symbol=series,
        sectors=[("XLK", "Technology"), ("XLU", "Utilities")],
    )
    assert snap.as_of == date(2026, 4, 28)


def test_universe_has_eleven_distinct_etfs():
    symbols = [s.symbol for s in SECTOR_ETFS]
    assert len(symbols) == 11
    assert len(set(symbols)) == 11


@pytest.mark.asyncio
async def test_service_uses_cache(monkeypatch):
    """Two calls within the TTL should hit yfinance only once."""
    sector_rotation_service._cache = None  # noqa: SLF001
    call_count = {"n": 0}

    def fake_download(symbols: list[str]):
        call_count["n"] += 1
        return {
            sym: _ramp(start=date(2026, 1, 2), days=70, base=100.0, daily_pct=0.001)
            for sym in symbols
        }

    with patch.object(
        sector_rotation_service,
        "_download_blocking",
        side_effect=fake_download,
    ):
        first = await sector_rotation_service.get_sector_rotation()
        second = await sector_rotation_service.get_sector_rotation()

    assert call_count["n"] == 1
    assert first["windows"] == ["1d", "5d", "1m", "3m", "ytd"]
    assert len(first["rows"]) == 11
    assert second["as_of"] == first["as_of"]


@pytest.mark.asyncio
async def test_service_force_refresh_bypasses_cache():
    sector_rotation_service._cache = None  # noqa: SLF001
    call_count = {"n": 0}

    def fake_download(symbols: list[str]):
        call_count["n"] += 1
        return {sym: _ramp(start=date(2026, 1, 2), days=10, base=100.0, daily_pct=0.001) for sym in symbols}

    with patch.object(
        sector_rotation_service,
        "_download_blocking",
        side_effect=fake_download,
    ):
        await sector_rotation_service.get_sector_rotation()
        await sector_rotation_service.get_sector_rotation(force=True)

    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_service_handles_empty_yfinance_response():
    """Empty download → 11 rows with None returns, no exceptions."""
    sector_rotation_service._cache = None  # noqa: SLF001
    with patch.object(
        sector_rotation_service,
        "_download_blocking",
        return_value={},
    ):
        payload = await sector_rotation_service.get_sector_rotation()
    assert len(payload["rows"]) == 11
    assert payload["as_of"] is None
    for row in payload["rows"]:
        assert row["latest_close"] is None
        assert all(v is None for v in row["returns"].values())
