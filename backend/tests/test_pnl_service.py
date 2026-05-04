"""PnL aggregation from the Trade table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.database import AsyncSessionLocal, Trade, init_database
from app.services import pnl_service


@pytest.fixture(autouse=True)
async def _isolate_trades(monkeypatch, tmp_path):
    """Each test runs against a fresh tmp DB so Trade rows don't leak."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "p5.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    # Re-export shim attributes:
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_realized_pnl_today_zero_when_no_trades() -> None:
    async with AsyncSessionLocal() as session:
        result = await pnl_service.realized_pnl_today(session)
    assert result == 0.0


@pytest.mark.asyncio
async def test_realized_pnl_today_sums_today_only() -> None:
    today = _now_utc()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=110, qty=10, net_profit=100.0, exit_reason="TAKE_PROFIT"))
        session.add(Trade(symbol="MSFT", entry_date=yesterday, exit_date=yesterday, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="NVDA", entry_date=today, exit_date=today, entry_price=900, exit_price=850, qty=2, net_profit=-100.0, exit_reason="STOP_LOSS"))
        await session.commit()
        result = await pnl_service.realized_pnl_today(session)
    # Today: +100 (AAPL) - 100 (NVDA) = 0. Yesterday's -100 (MSFT) excluded.
    assert result == 0.0


@pytest.mark.asyncio
async def test_realized_pnl_today_returns_negative_when_losing() -> None:
    today = _now_utc()
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=90, qty=10, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="MSFT", entry_date=today, exit_date=today, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        await session.commit()
        result = await pnl_service.realized_pnl_today(session)
    assert result == -200.0


@pytest.mark.asyncio
async def test_summary_returns_aggregated_stats() -> None:
    today = _now_utc()
    yesterday = today - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        session.add(Trade(symbol="AAPL", entry_date=today, exit_date=today, entry_price=100, exit_price=110, qty=10, net_profit=100.0, exit_reason="TAKE_PROFIT"))
        session.add(Trade(symbol="MSFT", entry_date=today, exit_date=today, entry_price=400, exit_price=380, qty=5, net_profit=-100.0, exit_reason="STOP_LOSS"))
        session.add(Trade(symbol="GOOG", entry_date=yesterday, exit_date=yesterday, entry_price=150, exit_price=160, qty=3, net_profit=30.0, exit_reason="TAKE_PROFIT"))
        await session.commit()
        summary = await pnl_service.daily_summary(session)
    assert summary["realized_pnl_today"] == 0.0
    assert summary["trades_today"] == 2
    assert summary["wins_today"] == 1
    assert summary["losses_today"] == 1
    assert summary["last_trade_at"] is not None


@pytest.mark.asyncio
async def test_recent_streak_counts_consecutive_outcomes() -> None:
    base = _now_utc() - timedelta(days=3)
    async with AsyncSessionLocal() as session:
        # Older first -> newer last so the streak is "two losses ending today".
        for i, pnl in enumerate([50.0, 50.0, -10.0, -20.0]):
            ts = base + timedelta(hours=i)
            session.add(Trade(
                symbol="X", entry_date=ts, exit_date=ts,
                entry_price=10, exit_price=10 + pnl / 1, qty=1,
                net_profit=pnl, exit_reason="TAKE_PROFIT" if pnl > 0 else "STOP_LOSS",
            ))
        await session.commit()
        streak = await pnl_service.recent_streak(session)
    assert streak["kind"] == "loss"
    assert streak["length"] == 2
