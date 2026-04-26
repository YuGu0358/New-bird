"""AlpacaBroker delegates to app.services.alpaca_service."""
from __future__ import annotations

from typing import Any

import pytest

from core.broker import AlpacaBroker


@pytest.mark.asyncio
async def test_list_positions_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel: list[dict[str, Any]] = [{"symbol": "AAPL", "qty": "10"}]

    async def fake_list_positions() -> list[dict[str, Any]]:
        return sentinel

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "list_positions", fake_list_positions)
    broker = AlpacaBroker()
    result = await broker.list_positions()
    assert result is sentinel


@pytest.mark.asyncio
async def test_submit_order_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_submit_order(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": "order-1", "symbol": kwargs.get("symbol")}

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "submit_order", fake_submit_order)
    broker = AlpacaBroker()
    response = await broker.submit_order(symbol="AAPL", side="buy", notional=1000.0)
    assert response["id"] == "order-1"
    assert captured == {"symbol": "AAPL", "side": "buy", "notional": 1000.0}


@pytest.mark.asyncio
async def test_close_position_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: dict[str, Any] = {}

    async def fake_close_position(symbol: str) -> dict[str, Any]:
        called_with["symbol"] = symbol
        return {"closed": symbol}

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "close_position", fake_close_position)
    broker = AlpacaBroker()
    response = await broker.close_position("MSFT")
    assert response == {"closed": "MSFT"}
    assert called_with == {"symbol": "MSFT"}


@pytest.mark.asyncio
async def test_list_orders_passes_status_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def fake_list_orders(**kwargs: Any) -> list[dict[str, Any]]:
        captured_kwargs.update(kwargs)
        return []

    from app.services import alpaca_service

    monkeypatch.setattr(alpaca_service, "list_orders", fake_list_orders)
    broker = AlpacaBroker()
    await broker.list_orders(status="open")
    assert captured_kwargs == {"status": "open"}
    captured_kwargs.clear()
    await broker.list_orders(status="all", limit=200)
    assert captured_kwargs == {"status": "all", "limit": 200}
