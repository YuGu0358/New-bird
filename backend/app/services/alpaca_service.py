from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app import runtime_settings


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    return None


def _read_value(source: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(source, dict) and key in source:
            return source[key]
        if hasattr(source, key):
            return getattr(source, key)

    raw_value = getattr(source, "_raw", None)
    if isinstance(raw_value, dict):
        for key in keys:
            if key in raw_value:
                return raw_value[key]

    return None


def _normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if base_url.endswith("/v2"):
        return base_url[:-3]
    return base_url


def _require_credentials() -> tuple[str, str, str]:
    api_key = runtime_settings.get_required_setting(
        "ALPACA_API_KEY",
        "Alpaca API credentials are missing. Configure them in the settings page or backend/.env first.",
    )
    secret_key = runtime_settings.get_required_setting(
        "ALPACA_SECRET_KEY",
        "Alpaca API credentials are missing. Configure them in the settings page or backend/.env first.",
    )
    base_url = _normalize_base_url(
        runtime_settings.get_setting("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        or "https://paper-api.alpaca.markets"
    )

    return api_key, secret_key, base_url


def _create_client():
    try:
        import alpaca_trade_api as tradeapi
    except ImportError as exc:
        raise RuntimeError("alpaca-trade-api is not installed.") from exc

    api_key, secret_key, base_url = _require_credentials()
    return tradeapi.REST(key_id=api_key, secret_key=secret_key, base_url=base_url)


async def get_account() -> dict[str, Any]:
    client = _create_client()
    account = await asyncio.to_thread(client.get_account)
    return {
        "account_id": getattr(account, "id", ""),
        "status": getattr(account, "status", "UNKNOWN"),
        "currency": getattr(account, "currency", "USD"),
        "cash": _to_float(getattr(account, "cash", 0.0)),
        "buying_power": _to_float(getattr(account, "buying_power", 0.0)),
        "equity": _to_float(getattr(account, "equity", 0.0)),
        "last_equity": _to_float(getattr(account, "last_equity", 0.0)),
    }


async def list_positions() -> list[dict[str, Any]]:
    client = _create_client()
    positions = await asyncio.to_thread(client.list_positions)
    return [
        {
            "symbol": getattr(position, "symbol", ""),
            "qty": _to_float(getattr(position, "qty", 0.0)),
            "entry_price": _to_float(getattr(position, "avg_entry_price", 0.0)),
            "current_price": _to_float(getattr(position, "current_price", 0.0)),
            "market_value": _to_float(getattr(position, "market_value", 0.0)),
            "unrealized_pl": _to_float(getattr(position, "unrealized_pl", 0.0)),
        }
        for position in positions
    ]


async def list_assets(
    *,
    status: str = "active",
    asset_class: str = "us_equity",
) -> list[dict[str, Any]]:
    """Return Alpaca assets for watchlist discovery and universe search."""

    client = _create_client()
    assets = await asyncio.to_thread(
        client.list_assets,
        status=status,
        asset_class=asset_class,
    )
    return [
        {
            "symbol": str(getattr(asset, "symbol", "")).upper(),
            "name": getattr(asset, "name", None),
            "exchange": getattr(asset, "exchange", None),
            "asset_class": str(getattr(asset, "class", getattr(asset, "asset_class", "")) or ""),
            "status": getattr(asset, "status", None),
            "tradable": bool(getattr(asset, "tradable", False)),
            "shortable": bool(getattr(asset, "shortable", False)),
            "fractionable": bool(getattr(asset, "fractionable", False)),
        }
        for asset in assets
        if str(getattr(asset, "symbol", "")).strip()
    ]


async def submit_order(
    symbol: str,
    side: str,
    *,
    qty: float | None = None,
    notional: float | None = None,
    order_type: str = "market",
    time_in_force: str = "day",
) -> dict[str, Any]:
    if (qty is None and notional is None) or (qty is not None and notional is not None):
        raise ValueError("Provide exactly one of qty or notional when submitting an order.")

    client = _create_client()
    order_payload = {
        "symbol": symbol,
        "side": side,
        "type": order_type,
        "time_in_force": time_in_force,
    }
    if qty is not None:
        order_payload["qty"] = qty
    if notional is not None:
        order_payload["notional"] = notional

    order = await asyncio.to_thread(
        client.submit_order,
        **order_payload,
    )
    return {
        "id": getattr(order, "id", ""),
        "symbol": getattr(order, "symbol", symbol),
        "side": getattr(order, "side", side),
        "status": getattr(order, "status", "accepted"),
    }


async def close_position(symbol: str) -> dict[str, Any]:
    client = _create_client()
    result = await asyncio.to_thread(client.close_position, symbol)
    return {
        "symbol": symbol,
        "status": getattr(result, "status", "submitted"),
    }


async def get_market_snapshots(symbols: list[str]) -> dict[str, dict[str, Any]]:
    client = _create_client()
    snapshots = await asyncio.to_thread(client.get_snapshots, symbols)
    normalized: dict[str, dict[str, Any]] = {}

    for symbol, snapshot in dict(snapshots).items():
        latest_trade = _read_value(snapshot, "latest_trade")
        minute_bar = _read_value(snapshot, "minute_bar")
        daily_bar = _read_value(snapshot, "daily_bar")
        prev_daily_bar = _read_value(snapshot, "prev_daily_bar")

        current_price = _to_float(
            _read_value(latest_trade, "price", "p")
            or _read_value(minute_bar, "close", "c")
            or _read_value(daily_bar, "close", "c")
        )
        previous_close = _to_float(_read_value(prev_daily_bar, "close", "c"))

        if current_price <= 0 or previous_close <= 0:
            continue

        normalized[str(symbol).upper()] = {
            "symbol": str(symbol).upper(),
            "price": current_price,
            "previous_close": previous_close,
            "timestamp": datetime.now(timezone.utc),
        }

    return normalized


async def list_orders(status: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    client = _create_client()
    orders = await asyncio.to_thread(
        client.list_orders,
        status=status,
        limit=limit,
        nested=False,
        direction="desc",
    )
    return [
        {
            "order_id": getattr(order, "id", ""),
            "symbol": getattr(order, "symbol", ""),
            "side": str(getattr(order, "side", "")),
            "order_type": str(getattr(order, "order_type", getattr(order, "type", ""))),
            "status": str(getattr(order, "status", "")),
            "qty": _to_float(getattr(order, "qty", None)) or None,
            "notional": _to_float(getattr(order, "notional", None)) or None,
            "filled_avg_price": _to_float(getattr(order, "filled_avg_price", None)) or None,
            "created_at": _to_datetime(getattr(order, "created_at", None)),
        }
        for order in orders
    ]


async def cancel_all_orders() -> int:
    client = _create_client()
    result = await asyncio.to_thread(client.cancel_all_orders)
    return len(result or [])


async def close_all_positions() -> int:
    client = _create_client()
    # Some alpaca-trade-api versions do not support the cancel_orders keyword,
    # so cancel open orders explicitly before closing positions.
    await asyncio.to_thread(client.cancel_all_orders)
    result = await asyncio.to_thread(client.close_all_positions)
    return len(result or [])
