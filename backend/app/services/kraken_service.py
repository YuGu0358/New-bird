"""Kraken convenience wrapper.

The public REST surface (ticker / trades / pairs) is exposed through
small functions here so the router stays thin. Mirrors the shape of
coingecko_service: opt-in gate, 5-min cache for ticker, no cache for
recent trades (they're inherently stale otherwise).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from core.broker import kraken as kraken_broker

logger = logging.getLogger(__name__)


_TICKER_CACHE_TTL = timedelta(minutes=1)
# Per-pair cache slot — pairs are short strings so this is plenty.
_ticker_cache: dict[str, tuple[datetime, dict[str, Any]]] = {}


def _reset_cache() -> None:
    _ticker_cache.clear()


async def get_ticker(pair: str, *, force: bool = False) -> dict[str, Any]:
    """Cached ticker fetch — 1 minute TTL is fine for retail dashboards."""
    now = datetime.now(timezone.utc)
    if not force:
        cached = _ticker_cache.get(pair)
        if cached and now - cached[0] <= _TICKER_CACHE_TTL:
            return cached[1]

    raw = await kraken_broker.fetch_ticker(pair)
    payload = {
        "pair": pair,
        "result": raw,
        "generated_at": now,
    }
    _ticker_cache[pair] = (now, payload)
    return payload


async def get_recent_trades(pair: str) -> dict[str, Any]:
    raw = await kraken_broker.fetch_recent_trades(pair)
    return {
        "pair": pair,
        "result": raw,
        "generated_at": datetime.now(timezone.utc),
    }
