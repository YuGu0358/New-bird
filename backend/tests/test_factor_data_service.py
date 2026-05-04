"""Unit tests for app.services.factor_data_service.

Alpaca calls are mocked at the `_fetch_bars_sync` boundary so the tests
never touch the network or require ALPACA_API_KEY/ALPACA_SECRET_KEY.

Each test gets a fresh tmp SQLite DB and rebinds AsyncSessionLocal in
both `engine` and the service module, mirroring the pattern used in
`test_position_snapshots.py`.
"""
from __future__ import annotations

import importlib
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test, with AsyncSessionLocal rebound everywhere
    factor_data_service references it (including the module's own
    closure-bound import)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine_module = importlib.import_module("app.db.engine")

    db_path = tmp_path / "factor_forge.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)

    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)

    from app import database as legacy

    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)

    from app.services import factor_data_service as svc

    monkeypatch.setattr(svc, "AsyncSessionLocal", new_session_factory)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    try:
        yield
    finally:
        await new_engine.dispose()


# ---------------------------------------------------------------------------
# compute_activity_score: pure-function math
# ---------------------------------------------------------------------------


def test_activity_score_ranks_most_active_first():
    from app.services.factor_data_service import compute_activity_score

    # Arrange — C should dominate on every component (largest dollar volume,
    # largest |return|, largest range fraction).
    today = pd.DataFrame(
        [
            {"symbol": "A", "open": 100, "high": 105, "low": 99, "close": 102,
             "volume": 1_000_000},
            {"symbol": "B", "open": 50, "high": 51, "low": 49, "close": 50,
             "volume": 500_000},
            {"symbol": "C", "open": 200, "high": 220, "low": 195, "close": 210,
             "volume": 5_000_000},
        ]
    )
    history = pd.DataFrame(
        [
            {"symbol": "A", "close": 100},
            {"symbol": "B", "close": 50},
            {"symbol": "C", "close": 195},
        ]
    )

    # Act
    scored = compute_activity_score(today, history)

    # Assert
    assert len(scored) == 3
    ranked = scored.sort_values("activity_score", ascending=False).reset_index(drop=True)
    assert ranked.iloc[0]["symbol"] == "C"


def test_activity_score_zscore_zero_when_uniform():
    """If every symbol has identical inputs, every z-score is 0
    (std=0 path), so activity_score should be 0 for all rows."""
    from app.services.factor_data_service import compute_activity_score

    today = pd.DataFrame(
        [
            {"symbol": "A", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
            {"symbol": "B", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
        ]
    )
    history = pd.DataFrame(
        [{"symbol": "A", "close": 10}, {"symbol": "B", "close": 10}]
    )

    scored = compute_activity_score(today, history)

    assert (scored["activity_score"] == 0).all()


def test_activity_score_handles_empty_history():
    from app.services.factor_data_service import compute_activity_score

    today = pd.DataFrame(
        [
            {"symbol": "A", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000},
            {"symbol": "B", "open": 20, "high": 22, "low": 18, "close": 20, "volume": 2000},
        ]
    )
    empty_history = pd.DataFrame(columns=["symbol", "close"])

    scored = compute_activity_score(today, empty_history)

    assert len(scored) == 2
    # vol_return_score is volume * |return|; with no history return=0.
    assert (scored["vol_return_score"] == 0).all()


def test_activity_score_empty_input_returns_empty():
    from app.services.factor_data_service import compute_activity_score

    out = compute_activity_score(
        pd.DataFrame(columns=["symbol", "open", "high", "low", "close", "volume"]),
        pd.DataFrame(columns=["symbol", "close"]),
    )
    assert out.empty


# ---------------------------------------------------------------------------
# update_active_universe + get_active_universe round-trip
# ---------------------------------------------------------------------------


async def _seed_bars(rows: list[dict]) -> None:
    """Insert DailyBar rows directly via the ORM."""
    from app.db.tables import DailyBar
    from app.services.factor_data_service import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        for r in rows:
            session.add(
                DailyBar(
                    symbol=r["symbol"],
                    date=r["date"],
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                    vwap=r.get("vwap"),
                )
            )
        await session.commit()


async def test_update_active_universe_writes_topn_sorted():
    from app.services.factor_data_service import (
        get_active_universe,
        update_active_universe,
    )

    target = date(2026, 4, 30)
    prev = target - timedelta(days=1)

    # Seed prior-day closes so |return| is well-defined.
    await _seed_bars(
        [
            {"symbol": "A", "date": prev, "open": 100, "high": 100, "low": 100,
             "close": 100, "volume": 1},
            {"symbol": "B", "date": prev, "open": 50, "high": 50, "low": 50,
             "close": 50, "volume": 1},
            {"symbol": "C", "date": prev, "open": 195, "high": 195, "low": 195,
             "close": 195, "volume": 1},
        ]
    )
    # Today: C is most active, A is mid, B is least.
    await _seed_bars(
        [
            {"symbol": "A", "date": target, "open": 100, "high": 105, "low": 99,
             "close": 102, "volume": 1_000_000},
            {"symbol": "B", "date": target, "open": 50, "high": 51, "low": 49,
             "close": 50, "volume": 500_000},
            {"symbol": "C", "date": target, "open": 200, "high": 220, "low": 195,
             "close": 210, "volume": 5_000_000},
        ]
    )

    written = await update_active_universe(target, top_n=2)
    assert written == 2

    # Top 2 ranked by activity_score, descending.
    top2 = await get_active_universe(target, top_n=2)
    assert len(top2) == 2
    assert top2[0] == "C"  # most active in front

    # Asking for a single symbol respects the limit.
    top1 = await get_active_universe(target, top_n=1)
    assert top1 == ["C"]


async def test_update_active_universe_idempotent_rewrite():
    """Calling twice for the same date should leave the same row count
    (DELETE-then-INSERT). The first call populates 3 rows, the second
    re-runs and should still produce 3 rows."""
    from app.services.factor_data_service import update_active_universe

    target = date(2026, 4, 30)
    await _seed_bars(
        [
            {"symbol": "A", "date": target, "open": 1, "high": 2, "low": 1,
             "close": 2, "volume": 100},
            {"symbol": "B", "date": target, "open": 1, "high": 3, "low": 1,
             "close": 2, "volume": 200},
            {"symbol": "C", "date": target, "open": 1, "high": 4, "low": 1,
             "close": 3, "volume": 300},
        ]
    )

    n1 = await update_active_universe(target, top_n=10)
    n2 = await update_active_universe(target, top_n=10)
    assert n1 == 3
    assert n2 == 3


async def test_get_active_universe_empty_date():
    from app.services.factor_data_service import get_active_universe

    result = await get_active_universe(date(2020, 1, 1))
    assert result == []


async def test_update_active_universe_no_bars_returns_zero():
    """No DailyBar rows for the date -> returns 0, no insert."""
    from app.services.factor_data_service import update_active_universe

    written = await update_active_universe(date(2020, 6, 1), top_n=10)
    assert written == 0


# ---------------------------------------------------------------------------
# get_panel
# ---------------------------------------------------------------------------


async def test_get_panel_filters_by_range_and_symbols():
    from app.services.factor_data_service import get_panel

    d0 = date(2026, 1, 1)
    d1 = date(2026, 1, 2)
    d2 = date(2026, 1, 3)
    await _seed_bars(
        [
            {"symbol": "A", "date": d0, "open": 1, "high": 1, "low": 1,
             "close": 1, "volume": 10},
            {"symbol": "A", "date": d1, "open": 2, "high": 2, "low": 2,
             "close": 2, "volume": 20},
            {"symbol": "B", "date": d1, "open": 3, "high": 3, "low": 3,
             "close": 3, "volume": 30},
            {"symbol": "A", "date": d2, "open": 4, "high": 4, "low": 4,
             "close": 4, "volume": 40},
        ]
    )

    panel = await get_panel(d0, d1)
    assert len(panel) == 3  # A on d0, A on d1, B on d1

    only_a = await get_panel(d0, d2, symbols=["A"])
    assert len(only_a) == 3
    # Confirm B isn't in the result.
    sym_index = only_a.index.get_level_values("symbol")
    assert "B" not in set(sym_index)


async def test_get_panel_empty_when_no_rows():
    from app.services.factor_data_service import get_panel

    panel = await get_panel(date(2000, 1, 1), date(2000, 1, 2))
    assert panel.empty


# ---------------------------------------------------------------------------
# update_daily_bars: mocks Alpaca, verifies persistence + missing-symbol case
# ---------------------------------------------------------------------------


async def test_update_daily_bars_persists_mocked_response(monkeypatch):
    """Alpaca returns 2 of 3 requested symbols. The missing one should
    just be absent from the DB — no exception, no fake row."""
    from app.db.tables import DailyBar
    from app.services import factor_data_service as svc
    from app.services.factor_data_service import AsyncSessionLocal
    from sqlalchemy import select

    captured_calls: list[tuple[list[str], date, date]] = []

    def _fake_fetch(symbols, start, end):
        captured_calls.append((list(symbols), start, end))
        # Return bars for AAPL + MSFT only; NVDA is silently dropped by Alpaca.
        return pd.DataFrame(
            [
                {"symbol": "AAPL", "date": date(2026, 4, 28), "open": 170.0,
                 "high": 172.0, "low": 169.0, "close": 171.0, "volume": 1_000_000,
                 "vwap": 170.5},
                {"symbol": "MSFT", "date": date(2026, 4, 28), "open": 410.0,
                 "high": 415.0, "low": 408.0, "close": 412.0, "volume": 800_000,
                 "vwap": 411.0},
            ]
        )

    monkeypatch.setattr(svc, "_fetch_bars_sync", _fake_fetch)

    inserted = await svc.update_daily_bars(symbols=["AAPL", "MSFT", "NVDA"])
    assert inserted == 2

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(select(DailyBar))).scalars().all()
        symbols = sorted(r.symbol for r in rows)
        assert symbols == ["AAPL", "MSFT"]
        # Sanity: stored values match what the mock returned.
        aapl = next(r for r in rows if r.symbol == "AAPL")
        assert aapl.close == 171.0
        assert aapl.vwap == 170.5

    # The fetch happened with all three symbols in the chunk.
    assert captured_calls
    requested_syms, _, _ = captured_calls[0]
    assert set(requested_syms) == {"AAPL", "MSFT", "NVDA"}


async def test_update_daily_bars_swallows_alpaca_errors(monkeypatch):
    """If Alpaca raises (e.g. auth failure), update_daily_bars logs and
    returns 0 instead of propagating. This means tests don't need real
    ALPACA keys — they only need the mock OR a raising mock."""
    from app.services import factor_data_service as svc

    def _boom(symbols, start, end):
        raise RuntimeError("Alpaca 401 unauthorized")

    monkeypatch.setattr(svc, "_fetch_bars_sync", _boom)

    inserted = await svc.update_daily_bars(symbols=["AAPL"])
    assert inserted == 0


# ---------------------------------------------------------------------------
# get_russell_universe: cache + fallback behavior, fetch is mocked
# ---------------------------------------------------------------------------


async def test_get_russell_universe_uses_cache_when_fresh():
    from app.services import factor_data_service as svc

    with patch.object(svc, "_load_cached_russell", return_value=["AAPL", "MSFT"]):
        result = await svc.get_russell_universe()
    assert result == ["AAPL", "MSFT"]


async def test_get_russell_universe_falls_back_on_fetch_error():
    from app.services import factor_data_service as svc

    with patch.object(svc, "_load_cached_russell", return_value=None), patch.object(
        svc, "_fetch_russell_csv_sync", side_effect=RuntimeError("network")
    ):
        result = await svc.get_russell_universe()
    # Falls back to the hand-coded list (~200 entries).
    assert len(result) > 100


async def test_get_russell_universe_falls_back_on_short_csv():
    from app.services import factor_data_service as svc

    with patch.object(svc, "_load_cached_russell", return_value=None), patch.object(
        svc, "_fetch_russell_csv_sync", return_value=["AAPL", "MSFT"]
    ):
        result = await svc.get_russell_universe()
    # Too few symbols -> fallback list kicks in.
    assert len(result) > 100


async def test_get_russell_universe_caches_to_disk():
    from app.services import factor_data_service as svc

    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "rus.json"
        symbols = [f"SYM{i:03d}" for i in range(800)]
        with patch.object(svc, "_RUSSELL_CACHE_PATH", cache_path), patch.object(
            svc, "_load_cached_russell", return_value=None
        ), patch.object(svc, "_fetch_russell_csv_sync", return_value=symbols):
            result = await svc.get_russell_universe()
        assert len(result) == 800
        assert cache_path.exists()
        with open(cache_path) as f:
            data = json.load(f)
        assert len(data["symbols"]) == 800
