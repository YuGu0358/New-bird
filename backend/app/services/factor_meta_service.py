"""Refreshes static-ish metadata (sector, industry, market cap) for the factor universe.

Pulls from yfinance.Ticker.info, which is a synchronous network call — we wrap each
fetch with `asyncio.to_thread` so the event loop stays free. The refresh logic is
incremental: rows whose `refreshed_at` is within the freshness window are skipped,
so a daily scheduler invocation only hits the upstream for genuinely stale rows.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.engine import AsyncSessionLocal
from app.db.tables import SymbolMeta

logger = logging.getLogger(__name__)

DEFAULT_MAX_AGE_DAYS = 7


def _fetch_meta_sync(symbol: str) -> dict | None:
    """Pull sector/industry/market_cap from yfinance Ticker.info.

    Returns None when yfinance is not installed, the request fails, or the
    upstream returned an empty payload — callers treat None as "skip this symbol".
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not installed; skipping meta fetch for %s", symbol)
        return None
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        logger.warning("yfinance fetch failed for %s", symbol, exc_info=True)
        return None
    if not info:
        return None

    market_cap_raw = info.get("marketCap")
    market_cap: float | None
    try:
        market_cap = float(market_cap_raw) if market_cap_raw else None
    except (TypeError, ValueError):
        market_cap = None

    return {
        "symbol": symbol.upper(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "market_cap": market_cap,
    }


async def refresh_symbol_meta(
    symbols: list[str],
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
) -> int:
    """Fetch + upsert metadata for ``symbols`` whose record is older than ``max_age_days``.

    Returns the number of rows actually upserted (excludes skipped-fresh and
    fetch-failed rows). Each upsert runs in its own transaction so a single
    upstream blip doesn't poison the whole batch.
    """
    if not symbols:
        return 0

    normalized = [s.upper() for s in symbols if s]
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(SymbolMeta.symbol, SymbolMeta.refreshed_at).where(
                    SymbolMeta.symbol.in_(normalized)
                )
            )
        ).all()
    fresh = {sym for sym, refreshed_at in rows if refreshed_at >= cutoff}
    stale = [s for s in normalized if s not in fresh]

    updated = 0
    for sym in stale:
        meta = await asyncio.to_thread(_fetch_meta_sync, sym)
        if not meta:
            continue
        async with AsyncSessionLocal() as session:
            existing = (
                await session.execute(select(SymbolMeta).where(SymbolMeta.symbol == sym))
            ).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if existing is None:
                session.add(
                    SymbolMeta(
                        symbol=meta["symbol"],
                        sector=meta["sector"],
                        industry=meta["industry"],
                        market_cap=meta["market_cap"],
                        refreshed_at=now,
                    )
                )
            else:
                existing.sector = meta["sector"]
                existing.industry = meta["industry"]
                existing.market_cap = meta["market_cap"]
                existing.refreshed_at = now
            try:
                await session.commit()
                updated += 1
            except Exception:
                await session.rollback()
                logger.warning("Meta upsert failed for %s", sym, exc_info=True)
    return updated
