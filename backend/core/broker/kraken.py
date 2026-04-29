"""Kraken broker — read-only public REST in this task.

Phase 6.5 ships the data path only. Live order placement raises
NotImplementedError so a future task can layer authenticated trading
without changing this module's read surface.

Public Kraken REST (no key required) covers what we need:
- /0/public/Ticker?pair=XBTUSD       — last/bid/ask + 24h volume
- /0/public/Trades?pair=XBTUSD       — recent trade prints
- /0/public/AssetPairs               — pair metadata

Kraken returns errors via a top-level `{"error": [...], "result": {}}`
envelope. We treat any non-empty error array as `KrakenAPIError` so
callers don't have to dig.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app import runtime_settings
from core.broker.base import Broker

logger = logging.getLogger(__name__)


_REQUEST_TIMEOUT = httpx.Timeout(5.0, connect=2.0)
_DEFAULT_API_BASE = "https://api.kraken.com"


class KrakenAPIError(RuntimeError):
    """Raised when Kraken responds with a non-empty error envelope."""


def _api_base() -> str:
    base = (
        runtime_settings.get_setting("KRAKEN_API_BASE", _DEFAULT_API_BASE)
        or _DEFAULT_API_BASE
    ).strip().rstrip("/")
    return base


def _ensure_enabled() -> None:
    if not runtime_settings.get_bool_setting("KRAKEN_ENABLED", default=False):
        raise RuntimeError(
            "Kraken integration is disabled. Set KRAKEN_ENABLED=true in settings to enable."
        )


async def _public_get(path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """One canonical entry point for every Kraken public call.

    Raises:
        KrakenAPIError when the upstream error array is non-empty.
        httpx.HTTPStatusError when the HTTP layer fails.
    """
    base = _api_base()
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.get(f"{base}{path}", params=params or {})
        response.raise_for_status()
        body = response.json()
    errors = body.get("error") or []
    if errors:
        raise KrakenAPIError("; ".join(str(e) for e in errors))
    return body.get("result") or {}


async def fetch_ticker(pair: str) -> dict[str, Any]:
    """Last/bid/ask + 24h volume for one pair (e.g., 'XBTUSD')."""
    _ensure_enabled()
    return await _public_get("/0/public/Ticker", params={"pair": pair})


async def fetch_recent_trades(pair: str, *, since: int | None = None) -> dict[str, Any]:
    """Recent trade prints for `pair`. Caller provides Kraken-style `since` cursor."""
    _ensure_enabled()
    params: dict[str, Any] = {"pair": pair}
    if since is not None:
        params["since"] = since
    return await _public_get("/0/public/Trades", params=params)


async def fetch_asset_pairs() -> dict[str, Any]:
    """Catalogue of every tradable pair with metadata."""
    _ensure_enabled()
    return await _public_get("/0/public/AssetPairs")


class KrakenBroker(Broker):
    """Concrete Broker for Kraken — read-only in this task.

    list_positions / list_orders / get_account return empty results so
    higher layers can probe shape without a key. submit_order and
    close_position raise NotImplementedError to make the paper-only
    contract explicit.
    """

    async def list_positions(self) -> list[dict[str, Any]]:
        return []

    async def list_orders(
        self,
        *,
        status: str = "all",
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        return []

    async def submit_order(
        self,
        *,
        symbol: str,
        side: str,
        notional: Optional[float] = None,
        qty: Optional[float] = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(
            "KrakenBroker is paper/read-only in this task; live trading lands in a follow-up plan"
        )

    async def close_position(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError(
            "KrakenBroker is paper/read-only in this task; live trading lands in a follow-up plan"
        )

    async def get_account(self) -> dict[str, Any]:
        # Until live trading is wired up, surface a deterministic stub
        # rather than a misleading "ACTIVE" — callers should expect None.
        return {
            "id": None,
            "status": "READ_ONLY",
            "currency": "USD",
            "equity": 0.0,
            "cash": 0.0,
            "buying_power": 0.0,
        }
