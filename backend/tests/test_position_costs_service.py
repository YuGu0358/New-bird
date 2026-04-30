"""Service-level tests for position_costs (cost basis + custom stops)."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp SQLite per test (mirrors test_workspace.py)."""
    import importlib
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine_module = importlib.import_module("app.db.engine")
    from app.database import AsyncSessionLocal

    original_engine = engine_module.engine
    db_path = tmp_path / "position_costs.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


async def _session():
    from app.database import AsyncSessionLocal
    return AsyncSessionLocal()


@pytest.mark.asyncio
async def test_list_empty_returns_zero_rows() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        result = await position_costs_service.list_for_account(s, broker_account_id=1)
    assert result == []


@pytest.mark.asyncio
async def test_record_buy_creates_row_with_avg_equal_to_fill_price() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        view = await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
    assert view["avg_cost_basis"] == 180.0
    assert view["total_shares"] == 10.0


@pytest.mark.asyncio
async def test_record_buy_recomputes_avg_on_second_buy() -> None:
    """First buy 10 @ 180. Second buy 10 @ 200. New avg = 190."""
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
        view = await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=200.0, fill_qty=10.0,
        )
    assert view["avg_cost_basis"] == pytest.approx(190.0)
    assert view["total_shares"] == 20.0


@pytest.mark.asyncio
async def test_upsert_replaces_avg_directly() -> None:
    """Manual upsert bypasses the running average — used to import existing positions."""
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.upsert(
            s, broker_account_id=1, ticker="AAPL",
            avg_cost_basis=150.0, total_shares=20.0,
            custom_stop_loss=140.0, custom_take_profit=180.0, notes="imported",
        )
        view = await position_costs_service.get_one(s, broker_account_id=1, ticker="AAPL")
    assert view is not None
    assert view["avg_cost_basis"] == 150.0
    assert view["custom_stop_loss"] == 140.0
    assert view["notes"] == "imported"


@pytest.mark.asyncio
async def test_get_one_returns_none_when_missing() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        view = await position_costs_service.get_one(s, broker_account_id=1, ticker="GHOST")
    assert view is None


@pytest.mark.asyncio
async def test_delete_returns_true_when_existed() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        await position_costs_service.record_buy(
            s, broker_account_id=1, ticker="NVDA", fill_price=180.0, fill_qty=10.0,
        )
        deleted = await position_costs_service.delete(s, broker_account_id=1, ticker="NVDA")
    assert deleted is True


@pytest.mark.asyncio
async def test_delete_returns_false_when_absent() -> None:
    from app.services import position_costs_service
    async with await _session() as s:
        deleted = await position_costs_service.delete(s, broker_account_id=1, ticker="GHOST")
    assert deleted is False
