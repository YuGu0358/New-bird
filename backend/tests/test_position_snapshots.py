"""Service- and router-level tests for the PositionSnapshot append-only table.

Mirrors the in-memory SQLite fixture pattern from
`test_position_overrides.py` — snapshots reference BrokerAccount rows,
so most tests seed an account first.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so PositionSnapshot rows don't leak.

    Why this is more invasive than test_position_overrides' fixture:
    `position_sync_service` does `from app.db.engine import
    AsyncSessionLocal` at import time, then calls `AsyncSessionLocal()`
    inside `snapshot_once`. Rebinding the engine_module attribute
    doesn't change the service's local symbol — we have to monkeypatch
    `position_sync_service.AsyncSessionLocal` directly so the service
    resolves to the per-test factory each run. Without this, sequential
    tests share a stale factory bound to the previous test's disposed
    engine, which deadlocks on the second connection attempt.
    """
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    db_path = tmp_path / "position_snapshots.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)

    # Patch every consumer's local symbol so they all see the new factory.
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    from app.services import position_sync_service as svc
    monkeypatch.setattr(svc, "AsyncSessionLocal", new_session_factory)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    try:
        # Expose the per-test factory globally on this test module so the
        # AsyncSessionLocal symbol imported at file top resolves to the
        # current test's factory (overrides the closure binding).
        import sys
        sys.modules[__name__].AsyncSessionLocal = new_session_factory
        yield
    finally:
        await new_engine.dispose()


async def _seed_ibkr_account(account_id: str = "DU123456") -> int:
    """Helper: create an IBKR BrokerAccount row and return its primary key."""
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="ibkr", account_id=account_id
        )
        return int(row["id"])


# ---------------------------------------------------------------------------
# 1. snapshot_once with no IBKR_ACCOUNT_ID -> returns 0, no rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_once_no_account_id_setting(monkeypatch) -> None:
    from app.services import position_sync_service as svc

    def _no_setting(key, default=""):
        return ""

    monkeypatch.setattr(
        svc.runtime_settings, "get_setting", _no_setting
    )
    written = await svc.snapshot_once()
    assert written == 0


# ---------------------------------------------------------------------------
# 2. snapshot_once with IBKR_ACCOUNT_ID set but no matching BrokerAccount
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_once_no_matching_broker_account(monkeypatch) -> None:
    from app.services import position_sync_service as svc

    monkeypatch.setattr(
        svc.runtime_settings,
        "get_setting",
        lambda key, default="": "DU999999",
    )

    async def _list_positions():
        return []

    monkeypatch.setattr(svc.ibkr_service, "list_positions", _list_positions)
    written = await svc.snapshot_once()
    assert written == 0


# ---------------------------------------------------------------------------
# 3. snapshot_once with matching account + 2 positions -> 2 rows written
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_once_writes_rows(monkeypatch) -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot
    from sqlalchemy import select

    pk = await _seed_ibkr_account("DU123456")

    monkeypatch.setattr(
        svc.runtime_settings,
        "get_setting",
        lambda key, default="": "DU123456",
    )

    async def _list_positions():
        return [
            {
                "symbol": "AAPL",
                "qty": 10.0,
                "avg_entry_price": 150.0,
                "market_value": 1700.0,
                "current_price": 170.0,
                "unrealized_pl": 200.0,
                "side": "long",
            },
            {
                "symbol": "MSFT",
                "qty": -5.0,
                "avg_entry_price": 300.0,
                "market_value": -1500.0,
                "current_price": 310.0,
                "unrealized_pl": -50.0,
                "side": "short",
            },
        ]

    monkeypatch.setattr(svc.ibkr_service, "list_positions", _list_positions)

    written = await svc.snapshot_once()
    assert written == 2

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PositionSnapshot))
        rows = list(result.scalars().all())
        assert len(rows) == 2
        symbols = {r.symbol for r in rows}
        assert symbols == {"AAPL", "MSFT"}
        for r in rows:
            assert r.broker_account_id == pk


# ---------------------------------------------------------------------------
# 4. snapshot_once when list_positions raises -> returns 0, no exception
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_once_swallows_fetch_errors(monkeypatch) -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot
    from sqlalchemy import select

    await _seed_ibkr_account("DU123456")

    monkeypatch.setattr(
        svc.runtime_settings,
        "get_setting",
        lambda key, default="": "DU123456",
    )

    async def _boom():
        raise RuntimeError("ib gateway not connected")

    monkeypatch.setattr(svc.ibkr_service, "list_positions", _boom)

    # Should not raise:
    written = await svc.snapshot_once()
    assert written == 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PositionSnapshot))
        assert list(result.scalars().all()) == []


# ---------------------------------------------------------------------------
# 5. snapshot_once skips empty-symbol or non-numeric-qty positions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_snapshot_once_skips_invalid_positions(monkeypatch) -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot
    from sqlalchemy import select

    await _seed_ibkr_account("DU123456")

    monkeypatch.setattr(
        svc.runtime_settings,
        "get_setting",
        lambda key, default="": "DU123456",
    )

    async def _list_positions():
        return [
            {"symbol": "", "qty": 10.0},  # empty symbol → skip
            {"symbol": "AAPL", "qty": "not-a-number"},  # bad qty → skip
            {"symbol": "TSLA", "qty": 7.0, "avg_entry_price": 200.0},  # ok
        ]

    monkeypatch.setattr(svc.ibkr_service, "list_positions", _list_positions)

    written = await svc.snapshot_once()
    assert written == 1

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(PositionSnapshot))
        rows = list(result.scalars().all())
        assert len(rows) == 1
        assert rows[0].symbol == "TSLA"


# ---------------------------------------------------------------------------
# 6. _safe_float corner cases
# ---------------------------------------------------------------------------


def test_safe_float_handles_edge_cases() -> None:
    from app.services.position_sync_service import _safe_float

    assert _safe_float(None) is None
    assert _safe_float("x") is None
    assert _safe_float(float("nan")) is None
    assert _safe_float(1.5) == 1.5
    assert _safe_float("2.25") == 2.25
    assert _safe_float(0) == 0.0


# ---------------------------------------------------------------------------
# 7. list_snapshots returns descending by snapshot_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_descending() -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot

    pk = await _seed_ibkr_account()
    base = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as session:
        for i in range(3):
            session.add(
                PositionSnapshot(
                    broker_account_id=pk,
                    symbol="AAPL",
                    snapshot_at=base + timedelta(minutes=i),
                    qty=float(i),
                    side="long",
                )
            )
        await session.commit()

    async with AsyncSessionLocal() as session:
        rows = await svc.list_snapshots(session, broker_account_id=pk)
        assert len(rows) == 3
        # Descending by snapshot_at
        assert rows[0]["snapshot_at"] >= rows[1]["snapshot_at"]
        assert rows[1]["snapshot_at"] >= rows[2]["snapshot_at"]


# ---------------------------------------------------------------------------
# 8. list_snapshots filter by broker_account_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_filter_by_account() -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot

    pk_a = await _seed_ibkr_account("DU-A")
    pk_b = await _seed_ibkr_account("DU-B")

    async with AsyncSessionLocal() as session:
        session.add(
            PositionSnapshot(broker_account_id=pk_a, symbol="AAPL", qty=1.0)
        )
        session.add(
            PositionSnapshot(broker_account_id=pk_b, symbol="MSFT", qty=2.0)
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        rows_a = await svc.list_snapshots(session, broker_account_id=pk_a)
        assert len(rows_a) == 1
        assert rows_a[0]["symbol"] == "AAPL"
        rows_b = await svc.list_snapshots(session, broker_account_id=pk_b)
        assert len(rows_b) == 1
        assert rows_b[0]["symbol"] == "MSFT"


# ---------------------------------------------------------------------------
# 9. list_snapshots filter by symbol (uppercase normalized)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_filter_by_symbol_normalized() -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot

    pk = await _seed_ibkr_account()

    async with AsyncSessionLocal() as session:
        session.add(
            PositionSnapshot(broker_account_id=pk, symbol="AAPL", qty=1.0)
        )
        session.add(
            PositionSnapshot(broker_account_id=pk, symbol="MSFT", qty=2.0)
        )
        await session.commit()

    async with AsyncSessionLocal() as session:
        # lower-case input normalizes:
        rows = await svc.list_snapshots(session, symbol="aapl")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"


# ---------------------------------------------------------------------------
# 10. list_snapshots filter by `since` cutoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_filter_by_since() -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot

    pk = await _seed_ibkr_account()
    base = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as session:
        for i in range(4):
            session.add(
                PositionSnapshot(
                    broker_account_id=pk,
                    symbol="AAPL",
                    snapshot_at=base + timedelta(minutes=i * 10),
                    qty=float(i),
                )
            )
        await session.commit()

    cutoff = base + timedelta(minutes=15)

    async with AsyncSessionLocal() as session:
        rows = await svc.list_snapshots(session, since=cutoff)
        # Only entries at minute 20 and 30 (>= cutoff)
        assert len(rows) == 2
        for r in rows:
            # SQLite (aiosqlite) loses tzinfo on read; normalize before compare.
            ts = r["snapshot_at"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            assert ts >= cutoff


# ---------------------------------------------------------------------------
# 11. list_snapshots clamps limit to [1, 1000]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_snapshots_clamps_limit() -> None:
    from app.services import position_sync_service as svc
    from app.db.tables import PositionSnapshot

    pk = await _seed_ibkr_account()
    base = datetime(2026, 4, 28, 12, 0, 0, tzinfo=timezone.utc)

    async with AsyncSessionLocal() as session:
        for i in range(5):
            session.add(
                PositionSnapshot(
                    broker_account_id=pk,
                    symbol="AAPL",
                    snapshot_at=base + timedelta(seconds=i),
                    qty=float(i),
                )
            )
        await session.commit()

    async with AsyncSessionLocal() as session:
        # limit=0 -> clamped to 1
        rows = await svc.list_snapshots(session, limit=0)
        assert len(rows) == 1

        # negative -> clamped to 1
        rows = await svc.list_snapshots(session, limit=-99)
        assert len(rows) == 1

        # 100000 -> clamped to 1000 (we only have 5 rows here, but the cap applies)
        rows = await svc.list_snapshots(session, limit=100000)
        assert len(rows) == 5  # less than cap; just shows it doesn't error


# ---------------------------------------------------------------------------
# 12. Router smoke: GET /api/portfolio/snapshots
# ---------------------------------------------------------------------------


async def test_router_get_snapshots() -> None:
    """Async router test using httpx.AsyncClient — avoids the
    `asyncio.get_event_loop().run_until_complete()` nested-loop deadlock
    that the original sync version hit when invoked inside the autouse
    async fixture's event loop."""
    from httpx import ASGITransport, AsyncClient

    from app.db.tables import PositionSnapshot
    from app.main import app
    from app.services import broker_accounts_service

    # Seed an IBKR broker account.
    async with AsyncSessionLocal() as session:
        account = await broker_accounts_service.create_account(
            session,
            broker="ibkr",
            account_id="DU-router-snap",
            alias="rtr",
            tier="TIER_1",
        )
    account_pk = account["id"]

    # Insert snapshot rows directly via the ORM (no scheduler involvement).
    async with AsyncSessionLocal() as session:
        session.add(
            PositionSnapshot(
                broker_account_id=account_pk,
                symbol="AAPL",
                qty=10.0,
                avg_cost=150.0,
                market_value=1700.0,
                current_price=170.0,
                unrealized_pl=200.0,
                side="long",
            )
        )
        session.add(
            PositionSnapshot(
                broker_account_id=account_pk,
                symbol="MSFT",
                qty=5.0,
                side="long",
            )
        )
        await session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/portfolio/snapshots",
            params={"broker_account_id": account_pk},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 2
    symbols = {it["symbol"] for it in items}
    assert symbols == {"AAPL", "MSFT"}
    for it in items:
        assert it["broker_account_id"] == account_pk
        assert "snapshot_at" in it
        assert "qty" in it
        assert "side" in it
