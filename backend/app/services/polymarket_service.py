"""Polymarket adapter — public gamma-api markets feed (opt-in).

Defaults to disabled because (a) US users have policy considerations around
prediction-market access, and (b) the integration is read-only commentary
data, not a primary signal — adding it to every fresh install would add
noise. Enable via the POLYMARKET_ENABLED setting.

Pattern mirrors `coingecko_service.py`: single-slot 5-minute cache, setting
gate checked before cache lookup, cache-fallback on httpx error, async
httpx client.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import runtime_settings
from core.predictions import (
    PredictionMarket,
    parse_markets_payload,
    sort_and_limit,
)

logger = logging.getLogger(__name__)


_CACHE_TTL = timedelta(minutes=5)
_REQUEST_TIMEOUT = httpx.Timeout(10.0, connect=4.0)
_DEFAULT_API_BASE = "https://gamma-api.polymarket.com"
# Polymarket lets us pull up to 100 markets in one go; we always pull the
# default page and trim on our side via sort_and_limit.
_UPSTREAM_PER_PAGE = 100

# Single global cache slot — keyed by the empty tuple because the upstream
# fetch ignores caller-side filters (we always pull a fresh active set and
# trim downstream). Format: (cached_at, payload).
_cache: tuple[datetime, dict[str, Any]] | None = None


def _reset_cache() -> None:
    """Test helper — wipe the cache between runs."""
    global _cache
    _cache = None


def _ensure_enabled() -> None:
    if not runtime_settings.get_bool_setting("POLYMARKET_ENABLED", default=False):
        raise RuntimeError(
            "Polymarket integration is disabled. Set POLYMARKET_ENABLED=true in settings to enable."
        )


def _api_base() -> str:
    base = (runtime_settings.get_setting("POLYMARKET_API_BASE", _DEFAULT_API_BASE) or _DEFAULT_API_BASE).strip()
    return base.rstrip("/")


async def _fetch_upstream() -> list[dict[str, Any]]:
    """Single httpx GET — returns the raw markets list or raises."""
    base = _api_base()
    params = {
        "limit": _UPSTREAM_PER_PAGE,
        "active": "true",
        "closed": "false",
        "order": "volume",
        "ascending": "false",
    }
    async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
        response = await client.get(f"{base}/markets", params=params)
        response.raise_for_status()
        data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(
            f"Polymarket /markets returned unexpected shape: {type(data).__name__}"
        )
    return data


def _row_to_dict(row: PredictionMarket) -> dict[str, Any]:
    return {
        "id": row.id,
        "question": row.question,
        "slug": row.slug,
        "category": row.category,
        "end_date": row.end_date,
        "closed": row.closed,
        "active": row.active,
        "volume_usd": row.volume_usd,
        "liquidity_usd": row.liquidity_usd,
        "yes_price": row.yes_price,
        "outcomes": [
            {"label": o.label, "price": o.price} for o in row.outcomes
        ],
    }


async def get_markets(
    *,
    limit: int = 25,
    sort_by: str = "volume_usd",
    descending: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Return the top-N prediction markets.

    Returns:
        {rows, total, limit, sort_by, descending, generated_at, as_of}.
    Raises:
        RuntimeError when POLYMARKET_ENABLED is not true. The router translates
        any RuntimeError whose message mentions "disabled" to HTTP 503.
        ValueError for unknown sort_by columns.
    """
    _ensure_enabled()

    global _cache
    now = datetime.now(timezone.utc)
    cached = _cache

    fresh_universe: list[PredictionMarket] | None = None
    if not force and cached is not None and now - cached[0] <= _CACHE_TTL:
        # Cache hit — use cached universe.
        cached_rows = cached[1].get("_universe") or []
        fresh_universe = [PredictionMarket(**r) if isinstance(r, dict) else r for r in cached_rows]

    if fresh_universe is None:
        try:
            raw = await _fetch_upstream()
            fresh_universe = parse_markets_payload(raw)
            _cache = (
                now,
                {
                    "_universe": fresh_universe,
                    "as_of": now,
                },
            )
        except Exception as exc:  # noqa: BLE001
            if cached is not None:
                logger.debug("Polymarket fetch failed; serving stale cache: %s", exc)
                fresh_universe = cached[1].get("_universe") or []
            else:
                raise RuntimeError(f"Polymarket fetch failed: {exc}") from exc

    selected = sort_and_limit(
        fresh_universe,
        limit=limit,
        sort_by=sort_by,
        descending=descending,
    )

    as_of = (cached[1].get("as_of") if (cached is not None and not force) else now)

    return {
        "rows": [_row_to_dict(r) for r in selected],
        # Universe count BEFORE trim — matches screener / coingecko semantics.
        "total": len(fresh_universe),
        "limit": limit,
        "sort_by": sort_by,
        "descending": descending,
        "generated_at": now,
        "as_of": as_of,
    }
