"""Top-level monitoring overview orchestrator."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import alpaca_service
from app.services.monitoring.candidates import build_candidate_pool
from app.services.monitoring.symbols import _normalize_symbols
from app.services.monitoring.trends import _empty_trend_snapshot, fetch_trend_snapshots
from app.services.monitoring.watchlist import (
    ensure_default_watchlist,
    get_alpaca_universe,
    get_selected_symbols,
)


async def get_monitoring_overview(
    session: AsyncSession,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Return the monitoring dashboard payload without altering trade logic."""

    await ensure_default_watchlist(session)

    selected_symbols = await get_selected_symbols(session)

    try:
        positions = await alpaca_service.list_positions()
    except Exception:
        positions = []

    position_symbols = [str(item.get("symbol", "")).upper() for item in positions if item.get("symbol")]
    candidate_pool = await build_candidate_pool(session, force_refresh=force_refresh)
    candidate_symbols = [str(item["symbol"]).upper() for item in candidate_pool]

    tracked_symbols = _normalize_symbols(selected_symbols + candidate_symbols + position_symbols)
    trend_map = await fetch_trend_snapshots(tracked_symbols, force_refresh=force_refresh)

    candidate_pool_payload = []
    now = datetime.now(timezone.utc)
    for item in candidate_pool:
        candidate_pool_payload.append(
            {
                "symbol": item["symbol"],
                "rank": item["rank"],
                "category": item["category"],
                "score": item["score"],
                "reason": item["reason"],
                "trend": trend_map.get(item["symbol"], _empty_trend_snapshot(item["symbol"], now)),
            }
        )

    tracked_payload = []
    candidate_set = set(candidate_symbols)
    selected_set = set(selected_symbols)
    position_set = set(position_symbols)

    for symbol in tracked_symbols:
        tags: list[str] = []
        if symbol in selected_set:
            tags.append("自选")
        if symbol in candidate_set:
            tags.append("候选")
        if symbol in position_set:
            tags.append("持仓")

        tracked_payload.append(
            {
                "symbol": symbol,
                "tags": tags,
                "trend": trend_map.get(symbol, _empty_trend_snapshot(symbol, now)),
            }
        )

    try:
        universe_asset_count = len(await get_alpaca_universe())
    except Exception:
        universe_asset_count = 0

    return {
        "generated_at": datetime.now(timezone.utc),
        "universe_asset_count": universe_asset_count,
        "selected_symbols": selected_symbols,
        "candidate_pool": candidate_pool_payload,
        "tracked_symbols": tracked_payload,
    }
