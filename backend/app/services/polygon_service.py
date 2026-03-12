from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from typing import Any

import httpx

from app import runtime_settings
from app.services import alpaca_service

POLYGON_REST_URL = "https://api.polygon.io"
TickHandler = Callable[[dict[str, Any]], Awaitable[None]]


def _api_key() -> str:
    return runtime_settings.get_required_setting(
        "POLYGON_API_KEY",
        "Polygon API key is missing. Configure it in the settings page or backend/.env first.",
    )


def _env_flag(name: str, default: bool = False) -> bool:
    return runtime_settings.get_bool_setting(name, default=default)


def _read_key(source: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(source, dict) and key in source:
            return source[key]
        if hasattr(source, key):
            return getattr(source, key)
    return None


def _extract_previous_close(payload: Any) -> float:
    results = _read_key(payload, "results")
    if isinstance(results, list) and results:
        close_value = _read_key(results[0], "c", "close")
        if close_value is not None:
            return float(close_value)
    close_value = _read_key(payload, "close", "c")
    if close_value is None:
        raise ValueError("Polygon previous-close response did not include a close price.")
    return float(close_value)


def _extract_last_trade(payload: Any) -> float:
    results = _read_key(payload, "results", "last")
    if results is not None:
        price = _read_key(results, "p", "price")
        if price is not None:
            return float(price)
    price = _read_key(payload, "price", "p")
    if price is None:
        raise ValueError("Polygon last-trade response did not include a trade price.")
    return float(price)


async def _sdk_previous_close(symbol: str) -> float:
    try:
        from polygon import RESTClient
    except ImportError as exc:
        raise RuntimeError("Polygon SDK is not installed.") from exc

    def _call() -> Any:
        client = RESTClient(api_key=_api_key())
        return client.get_previous_close(symbol)

    response = await asyncio.to_thread(_call)
    return _extract_previous_close(response)


async def _sdk_last_trade(symbol: str) -> float:
    try:
        from polygon import RESTClient
    except ImportError as exc:
        raise RuntimeError("Polygon SDK is not installed.") from exc

    def _call() -> Any:
        client = RESTClient(api_key=_api_key())
        return client.get_last_trade(symbol)

    response = await asyncio.to_thread(_call)
    return _extract_last_trade(response)


async def _http_get_json(path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{POLYGON_REST_URL}{path}",
            params={"apiKey": _api_key()},
        )
        response.raise_for_status()
        return response.json()


async def _rest_previous_close(symbol: str) -> float:
    payload = await _http_get_json(f"/v2/aggs/ticker/{symbol}/prev")
    return _extract_previous_close(payload)


async def _rest_last_trade(symbol: str) -> float:
    payload = await _http_get_json(f"/v2/last/trade/{symbol}")
    return _extract_last_trade(payload)


async def get_previous_close(symbol: str) -> float:
    try:
        return await _sdk_previous_close(symbol)
    except Exception:
        return await _rest_previous_close(symbol)


async def get_last_trade(symbol: str) -> float:
    try:
        return await _sdk_last_trade(symbol)
    except Exception:
        return await _rest_last_trade(symbol)


async def _run_sdk_stream(symbols: Sequence[str], on_tick: TickHandler) -> None:
    try:
        from polygon import WebSocketClient
    except ImportError as exc:
        raise RuntimeError("Polygon WebSocket client is not installed.") from exc

    loop = asyncio.get_running_loop()
    feed = runtime_settings.get_setting("POLYGON_FEED", "delayed") or "delayed"
    ws_client = WebSocketClient(api_key=_api_key(), feed=feed)

    for symbol in symbols:
        ws_client.subscribe(f"T.{symbol}")

    def handle_msg(messages: list[Any]) -> None:
        for message in messages:
            symbol = _read_key(message, "symbol", "sym", "ticker")
            price = _read_key(message, "price", "p")
            if not symbol or price is None:
                continue

            payload = {
                "symbol": str(symbol).upper(),
                "price": float(price),
                "timestamp": datetime.now(timezone.utc),
            }
            asyncio.run_coroutine_threadsafe(on_tick(payload), loop)

    await asyncio.to_thread(ws_client.run, handle_msg)


async def _run_polling_stream(
    symbols: Sequence[str],
    on_tick: TickHandler,
    poll_seconds: int,
) -> None:
    while True:
        try:
            snapshots = await alpaca_service.get_market_snapshots(list(symbols))
        except Exception:
            snapshots = {}

        if snapshots:
            for symbol in symbols:
                snapshot = snapshots.get(symbol)
                if snapshot is None:
                    continue
                await on_tick(snapshot)
            await asyncio.sleep(poll_seconds)
            continue

        previous_close_cache: dict[str, float] = {}

        async def emit(symbol: str) -> None:
            previous_close = previous_close_cache.get(symbol)
            if previous_close is None:
                previous_close = await get_previous_close(symbol)
                previous_close_cache[symbol] = previous_close

            last_trade = await get_last_trade(symbol)
            await on_tick(
                {
                    "symbol": symbol,
                    "price": last_trade,
                    "previous_close": previous_close,
                    "timestamp": datetime.now(timezone.utc),
                }
            )

        for symbol in symbols:
            try:
                await emit(symbol)
                await asyncio.sleep(0.4)
            except Exception:
                continue

        await asyncio.sleep(poll_seconds)


async def stream_quotes(
    symbols: Sequence[str],
    on_tick: TickHandler,
    poll_seconds: int = 15,
) -> None:
    if _env_flag("POLYGON_USE_WEBSOCKET", default=False):
        try:
            await _run_sdk_stream(symbols, on_tick)
            return
        except Exception:
            pass

    await _run_polling_stream(symbols, on_tick, poll_seconds)
