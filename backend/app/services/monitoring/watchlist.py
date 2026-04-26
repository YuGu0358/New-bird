"""Watchlist persistence + Alpaca asset universe queries."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import WatchlistSymbol
from app.services import alpaca_service
from app.services.monitoring.symbols import _normalize_symbol

DEFAULT_SELECTED_SYMBOLS = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "PG",
    "XOM",
    "KO",
    "PEP",
    "DIS",
    "CRM",
    "NFLX",
    "COST",
]

UNIVERSE_CACHE_TTL = timedelta(hours=12)

_universe_cache: dict[str, Any] = {"fetched_at": None, "items": []}


async def ensure_default_watchlist(session: AsyncSession) -> None:
    """Seed the default watchlist for first-time project startup."""

    result = await session.execute(select(WatchlistSymbol.id).limit(1))
    if result.first() is not None:
        return

    for symbol in DEFAULT_SELECTED_SYMBOLS:
        session.add(WatchlistSymbol(symbol=symbol))

    await session.commit()


async def get_selected_symbols(session: AsyncSession) -> list[str]:
    result = await session.execute(
        select(WatchlistSymbol).order_by(WatchlistSymbol.created_at, WatchlistSymbol.symbol)
    )
    return [row.symbol for row in result.scalars().all()]


async def add_watchlist_symbol(session: AsyncSession, symbol: str) -> list[str]:
    normalized_symbol = _normalize_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("股票代码不能为空。")

    result = await session.execute(
        select(WatchlistSymbol).where(WatchlistSymbol.symbol == normalized_symbol)
    )
    existing = result.scalars().first()
    if existing is None:
        session.add(WatchlistSymbol(symbol=normalized_symbol))
        await session.commit()

    return await get_selected_symbols(session)


async def remove_watchlist_symbol(session: AsyncSession, symbol: str) -> list[str]:
    normalized_symbol = _normalize_symbol(symbol)
    await session.execute(delete(WatchlistSymbol).where(WatchlistSymbol.symbol == normalized_symbol))
    await session.commit()
    return await get_selected_symbols(session)


async def get_alpaca_universe(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    cached_at = _universe_cache.get("fetched_at")
    cached_items = _universe_cache.get("items") or []

    if (
        not force_refresh
        and isinstance(cached_at, datetime)
        and now - cached_at <= UNIVERSE_CACHE_TTL
        and cached_items
    ):
        return list(cached_items)

    assets = await alpaca_service.list_assets(status="active", asset_class="us_equity")
    normalized_assets = sorted(
        (
            asset
            for asset in assets
            if asset.get("tradable") and asset.get("symbol")
        ),
        key=lambda asset: str(asset.get("symbol", "")),
    )
    _universe_cache["fetched_at"] = now
    _universe_cache["items"] = normalized_assets
    return list(normalized_assets)


async def search_alpaca_universe(query: str = "", limit: int = 50) -> list[dict[str, Any]]:
    assets = await get_alpaca_universe()
    normalized_query = query.strip().upper()

    if normalized_query:
        filtered = [
            asset
            for asset in assets
            if normalized_query in str(asset.get("symbol", "")).upper()
            or normalized_query in str(asset.get("name", "")).upper()
        ]
        filtered.sort(
            key=lambda asset: (
                str(asset.get("symbol", "")).upper() != normalized_query,
                not str(asset.get("symbol", "")).upper().startswith(normalized_query),
                normalized_query not in str(asset.get("symbol", "")).upper(),
                normalized_query not in str(asset.get("name", "")).upper(),
                str(asset.get("symbol", "")).upper(),
            )
        )
    else:
        filtered = assets

    return filtered[: max(1, min(limit, 200))]
