"""IBKRBroker delegates to app.services.ibkr_service; broker factory selects backend."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from core.broker import AlpacaBroker, IBKRBroker, get_broker


# --------------------------------------------------------------------------- #
# IBKRBroker delegation                                                       #
# --------------------------------------------------------------------------- #


async def test_get_account_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel: dict[str, Any] = {
        "id": "DU1234567",
        "status": "PAPER",
        "currency": "USD",
        "equity": 10000.0,
        "cash": 5000.0,
        "buying_power": 20000.0,
    }

    async def fake_get_account() -> dict[str, Any]:
        return sentinel

    from app.services import ibkr_service

    monkeypatch.setattr(ibkr_service, "get_account", fake_get_account)
    broker = IBKRBroker()
    result = await broker.get_account()
    assert result is sentinel


async def test_list_positions_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel: list[dict[str, Any]] = [{"symbol": "AAPL", "qty": 10.0}]

    async def fake_list_positions() -> list[dict[str, Any]]:
        return sentinel

    from app.services import ibkr_service

    monkeypatch.setattr(ibkr_service, "list_positions", fake_list_positions)
    broker = IBKRBroker()
    result = await broker.list_positions()
    assert result is sentinel


async def test_list_orders_forwards_status_and_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    async def fake_list_orders(**kwargs: Any) -> list[dict[str, Any]]:
        captured.append(dict(kwargs))
        return []

    from app.services import ibkr_service

    monkeypatch.setattr(ibkr_service, "list_orders", fake_list_orders)
    broker = IBKRBroker()
    # Without limit → only status flows through; limit omitted entirely.
    await broker.list_orders(status="open")
    # With limit → both kwargs forwarded as-is.
    await broker.list_orders(status="closed", limit=50)
    assert captured == [
        {"status": "open"},
        {"status": "closed", "limit": 50},
    ]


async def test_submit_order_forwards_all_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_submit_order(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": "order-7", "symbol": kwargs.get("symbol")}

    from app.services import ibkr_service

    monkeypatch.setattr(ibkr_service, "submit_order", fake_submit_order)
    broker = IBKRBroker()
    response = await broker.submit_order(
        symbol="MSFT",
        side="buy",
        notional=2500.0,
        qty=None,
    )
    assert response["id"] == "order-7"
    # All four named kwargs flow through, including notional=None / qty=None
    assert captured == {
        "symbol": "MSFT",
        "side": "buy",
        "notional": 2500.0,
        "qty": None,
    }


async def test_close_position_forwards_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: dict[str, Any] = {}

    async def fake_close_position(symbol: str) -> dict[str, Any]:
        called_with["symbol"] = symbol
        return {"closed": symbol}

    from app.services import ibkr_service

    monkeypatch.setattr(ibkr_service, "close_position", fake_close_position)
    broker = IBKRBroker()
    response = await broker.close_position("TSLA")
    assert response == {"closed": "TSLA"}
    assert called_with == {"symbol": "TSLA"}


# --------------------------------------------------------------------------- #
# get_broker() factory                                                        #
# --------------------------------------------------------------------------- #


def test_get_broker_returns_alpaca_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset BROKER_BACKEND → AlpacaBroker default."""
    from app import runtime_settings

    def fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key == "BROKER_BACKEND":
            return default
        return runtime_settings.get_setting(key, default)

    monkeypatch.setattr(runtime_settings, "get_setting", fake_get_setting)
    broker = get_broker()
    assert isinstance(broker, AlpacaBroker)


def test_get_broker_returns_ibkr_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """BROKER_BACKEND='ibkr' → IBKRBroker."""
    from app import runtime_settings

    def fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key == "BROKER_BACKEND":
            return "ibkr"
        return runtime_settings.get_setting(key, default)

    monkeypatch.setattr(runtime_settings, "get_setting", fake_get_setting)
    broker = get_broker()
    assert isinstance(broker, IBKRBroker)


def test_get_broker_unknown_value_falls_back_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown BROKER_BACKEND → AlpacaBroker fallback, with a WARNING log."""
    from app import runtime_settings
    from core import broker as broker_pkg

    def fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key == "BROKER_BACKEND":
            return "tradier"
        return runtime_settings.get_setting(key, default)

    monkeypatch.setattr(runtime_settings, "get_setting", fake_get_setting)
    with caplog.at_level(logging.WARNING, logger=broker_pkg.__name__):
        result = get_broker()

    assert isinstance(result, AlpacaBroker)
    # A warning was emitted that mentions the unknown value
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING log when BROKER_BACKEND is unknown"
    assert any("tradier" in record.getMessage() for record in warnings)
