"""CoinGecko adapter — top-N crypto markets via the free public REST API.

Opt-in via `CRYPTO_COINGECKO_ENABLED`. The setting gate is checked BEFORE
the cache lookup so disabling the integration always raises immediately,
even if a stale payload is sitting in memory from a prior enabled run.

Caching shape mirrors `sector_rotation_service`: a single global slot keyed
by `vs_currency=usd` with a 5-minute TTL. We always pull a full page of 250
rows from upstream so the user can change `limit` without triggering another
network round-trip.

Failure modes:
- Disabled setting → RuntimeError mentioning "disabled" (router maps to 503).
- httpx error AND cache populated → return cached payload (DEBUG-log).
- httpx error AND cache empty → RuntimeError surfaces.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app import runtime_settings
from core.crypto import (
    CryptoMarketRow,
    parse_markets_payload,
    sort_and_limit,
)

logger = logging.getLogger(__name__)


_DEFAULT_API_BASE = "https://api.coingecko.com/api/v3"
_CACHE_TTL = timedelta(minutes=5)
_TIMEOUT = httpx.Timeout(10.0, connect=4.0)
_UPSTREAM_PER_PAGE = 250

# (cached_at, {rows: list[CryptoMarketRow], as_of: datetime})
_cache: tuple[datetime, dict[str, Any]] | None = None


def _ensure_enabled() -> None:
    """Setting gate — raise the canonical disabled error if not opted-in."""
    enabled = runtime_settings.get_bool_setting(
        "CRYPTO_COINGECKO_ENABLED", default=False
    )
    if not enabled:
        raise RuntimeError(
            "CoinGecko integration is disabled. "
            "Set CRYPTO_COINGECKO_ENABLED=true in settings to enable."
        )


def _api_base() -> str:
    base = runtime_settings.get_setting("CRYPTO_COINGECKO_API_BASE", _DEFAULT_API_BASE)
    return (base or _DEFAULT_API_BASE).rstrip("/")


async def _fetch_upstream() -> list[CryptoMarketRow]:
    """One async GET against `/coins/markets` — returns parsed rows.

    Always asks for `per_page=250` so a single fetch covers any user-side
    `limit` choice between 1 and 250. We do not retry; httpx failures bubble
    up to the caller, which then decides between cache fallback and raise.
    """
    url = f"{_api_base()}/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": _UPSTREAM_PER_PAGE,
        "page": 1,
        "price_change_percentage": "24h",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        items = response.json() or []
    if not isinstance(items, list):
        logger.debug("CoinGecko returned non-list payload: %r", type(items))
        return []
    return parse_markets_payload(items)


async def _refresh_cache() -> dict[str, Any]:
    """Pull a fresh upstream page, replace the cache slot, return the payload."""
    global _cache

    rows = await _fetch_upstream()
    now = datetime.now(timezone.utc)
    payload = {"rows": rows, "as_of": now}
    _cache = (now, payload)
    return payload


async def get_markets(
    *,
    limit: int = 100,
    sort_by: str = "volume_24h_usd",
    descending: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Return the top-N crypto markets payload.

    Returns:
        {rows, total, limit, sort_by, descending, generated_at, as_of}
        with `rows` as a list of dicts.

    Raises:
        RuntimeError: when `CRYPTO_COINGECKO_ENABLED` is not true, or when
            the upstream fetch fails AND the cache is empty.
        ValueError: when `sort_by` is not a recognized column (raised from
            `sort_and_limit`).
    """
    _ensure_enabled()

    global _cache

    now = datetime.now(timezone.utc)
    cache_is_fresh = _cache is not None and now - _cache[0] <= _CACHE_TTL

    if force or not cache_is_fresh:
        try:
            payload = await _refresh_cache()
        except Exception as exc:
            if _cache is not None:
                logger.debug(
                    "CoinGecko fetch failed; serving stale cache: %s", exc
                )
                payload = _cache[1]
            else:
                raise RuntimeError(
                    f"CoinGecko fetch failed and no cache is available: {exc}"
                ) from exc
    else:
        payload = _cache[1]

    universe_rows: list[CryptoMarketRow] = payload.get("rows", [])
    as_of: datetime | None = payload.get("as_of")

    selected = sort_and_limit(
        universe_rows,
        limit=limit,
        sort_by=sort_by,
        descending=descending,
    )

    return {
        "rows": [_row_to_dict(r) for r in selected],
        # Universe size BEFORE the top-N trim — matches `screener_service`
        # semantics so the UI can render "showing N of TOTAL".
        "total": len(universe_rows),
        "limit": max(1, min(int(limit), 250)),
        "sort_by": sort_by,
        "descending": descending,
        "generated_at": datetime.now(timezone.utc),
        "as_of": as_of,
    }


def _row_to_dict(row: CryptoMarketRow) -> dict[str, Any]:
    return {
        "coin_id": row.coin_id,
        "symbol": row.symbol,
        "name": row.name,
        "rank": row.rank,
        "price_usd": row.price_usd,
        "market_cap_usd": row.market_cap_usd,
        "volume_24h_usd": row.volume_24h_usd,
        "change_24h_pct": row.change_24h_pct,
        "image_url": row.image_url,
    }
