"""Service tests for trade_recommendation_service.

Stubs chart_service + signals_service so the rule logic is the only
thing under test.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    import importlib
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine_module = importlib.import_module("app.db.engine")
    from app.database import AsyncSessionLocal

    original_engine = engine_module.engine
    db_path = tmp_path / "trade_rec.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
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


def _chart_with_close(price: float):
    return {
        "symbol": "TEST", "range": "3mo", "interval": "1d",
        "points": [{
            "timestamp": datetime(2026, 4, 30, tzinfo=timezone.utc),
            "open": price, "high": price * 1.01, "low": price * 0.99,
            "close": price, "volume": 1_000_000,
        }],
        "generated_at": datetime.now(timezone.utc),
    }


def _signals_payload(signals: list[dict]):
    return {
        "symbol": "TEST", "range": "3mo", "interval": "1d",
        "signals": signals, "generated_at": datetime.now(timezone.utc),
    }


@pytest.mark.asyncio
async def test_stop_loss_triggered_short_circuits_other_signals() -> None:
    """When current_price <= custom_stop_loss, only the stop stance is returned."""
    from app.services import trade_recommendation_service, position_costs_service
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await position_costs_service.upsert(
            s, broker_account_id=1, ticker="NVDA",
            avg_cost_basis=200.0, total_shares=10.0,
            custom_stop_loss=160.0, custom_take_profit=220.0,
        )

    bullish = _signals_payload([
        {"kind": "macd_bull_cross", "direction": "buy", "strength": 0.9,
         "ts": "2026-04-29T00:00:00+00:00", "bar_index": 50, "interpretation": "bull cross"},
    ])

    with patch("app.services.trade_recommendation_service.chart_service.get_symbol_chart",
               new=AsyncMock(return_value=_chart_with_close(155.0))), \
         patch("app.services.trade_recommendation_service.signals_service.compute_for_symbol",
               new=AsyncMock(return_value=bullish)):
        async with AsyncSessionLocal() as s:
            rec = await trade_recommendation_service.recommend_for_symbol(
                s, symbol="NVDA", broker_account_id=1
            )

    assert rec["has_position"] is True
    assert len(rec["stances"]) == 1
    assert rec["stances"][0]["action"] == "stop_triggered"


@pytest.mark.asyncio
async def test_take_profit_triggered_short_circuits() -> None:
    from app.services import trade_recommendation_service, position_costs_service
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as s:
        await position_costs_service.upsert(
            s, broker_account_id=1, ticker="AAPL",
            avg_cost_basis=150.0, total_shares=10.0,
            custom_take_profit=200.0,
        )

    with patch("app.services.trade_recommendation_service.chart_service.get_symbol_chart",
               new=AsyncMock(return_value=_chart_with_close(205.0))), \
         patch("app.services.trade_recommendation_service.signals_service.compute_for_symbol",
               new=AsyncMock(return_value=_signals_payload([]))):
        async with AsyncSessionLocal() as s:
            rec = await trade_recommendation_service.recommend_for_symbol(
                s, symbol="AAPL", broker_account_id=1
            )

    assert rec["stances"][0]["action"] == "tp_triggered"


@pytest.mark.asyncio
async def test_buy_dominance_emits_buy_when_no_position() -> None:
    from app.services import trade_recommendation_service
    from app.database import AsyncSessionLocal

    sigs = _signals_payload([
        {"kind": "rsi_oversold_bounce", "direction": "buy", "strength": 0.8,
         "ts": "2026-04-29T00:00:00+00:00", "bar_index": 50, "interpretation": "RSI bounce"},
        {"kind": "volume_breakout", "direction": "buy", "strength": 0.7,
         "ts": "2026-04-30T00:00:00+00:00", "bar_index": 51, "interpretation": "vol breakout"},
    ])

    with patch("app.services.trade_recommendation_service.chart_service.get_symbol_chart",
               new=AsyncMock(return_value=_chart_with_close(180.0))), \
         patch("app.services.trade_recommendation_service.signals_service.compute_for_symbol",
               new=AsyncMock(return_value=sigs)):
        async with AsyncSessionLocal() as s:
            rec = await trade_recommendation_service.recommend_for_symbol(
                s, symbol="NVDA", broker_account_id=1
            )

    assert rec["has_position"] is False
    assert rec["stances"][0]["action"] == "buy"
    assert rec["stances"][0]["confidence"] > 0


@pytest.mark.asyncio
async def test_no_signals_yields_wait_or_hold() -> None:
    from app.services import trade_recommendation_service
    from app.database import AsyncSessionLocal

    with patch("app.services.trade_recommendation_service.chart_service.get_symbol_chart",
               new=AsyncMock(return_value=_chart_with_close(100.0))), \
         patch("app.services.trade_recommendation_service.signals_service.compute_for_symbol",
               new=AsyncMock(return_value=_signals_payload([]))):
        async with AsyncSessionLocal() as s:
            rec = await trade_recommendation_service.recommend_for_symbol(
                s, symbol="X", broker_account_id=1
            )

    assert rec["stances"][0]["action"] in {"hold", "wait"}


@pytest.mark.asyncio
async def test_mixed_signals_yields_wait() -> None:
    from app.services import trade_recommendation_service
    from app.database import AsyncSessionLocal

    sigs = _signals_payload([
        {"kind": "rsi_oversold_bounce", "direction": "buy", "strength": 0.5,
         "ts": "2026-04-29T00:00:00+00:00", "bar_index": 50, "interpretation": "RSI bounce"},
        {"kind": "volume_breakdown", "direction": "sell", "strength": 0.5,
         "ts": "2026-04-30T00:00:00+00:00", "bar_index": 51, "interpretation": "vol break down"},
    ])

    with patch("app.services.trade_recommendation_service.chart_service.get_symbol_chart",
               new=AsyncMock(return_value=_chart_with_close(100.0))), \
         patch("app.services.trade_recommendation_service.signals_service.compute_for_symbol",
               new=AsyncMock(return_value=sigs)):
        async with AsyncSessionLocal() as s:
            rec = await trade_recommendation_service.recommend_for_symbol(
                s, symbol="X", broker_account_id=1
            )

    assert rec["stances"][0]["action"] == "wait"
