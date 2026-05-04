"""Aggregate the Trade table into PnL summaries.

Backed by SQL queries over `Trade` rows (closed round-trips). All
timestamps are UTC; "today" = `[utc_midnight_today, utc_midnight_tomorrow)`.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Trade


def _utc_today_window() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


async def realized_pnl_today(session: AsyncSession) -> float:
    """Sum of net_profit on Trade rows whose exit_date falls today (UTC)."""
    start, end = _utc_today_window()
    result = await session.execute(
        select(func.coalesce(func.sum(Trade.net_profit), 0.0)).where(
            Trade.exit_date >= start, Trade.exit_date < end
        )
    )
    return float(result.scalar_one())


async def daily_summary(session: AsyncSession) -> dict[str, Any]:
    """Today-only stats: total PnL, trade count, win/loss split, last trade timestamp."""
    start, end = _utc_today_window()

    pnl_result = await session.execute(
        select(func.coalesce(func.sum(Trade.net_profit), 0.0)).where(
            Trade.exit_date >= start, Trade.exit_date < end
        )
    )
    total_pnl = float(pnl_result.scalar_one())

    trades_result = await session.execute(
        select(Trade)
        .where(Trade.exit_date >= start, Trade.exit_date < end)
        .order_by(desc(Trade.exit_date))
    )
    trades = list(trades_result.scalars().all())
    wins = sum(1 for t in trades if t.net_profit > 0)
    losses = sum(1 for t in trades if t.net_profit < 0)
    last_trade_at: Optional[datetime] = trades[0].exit_date if trades else None

    return {
        "realized_pnl_today": total_pnl,
        "trades_today": len(trades),
        "wins_today": wins,
        "losses_today": losses,
        "last_trade_at": last_trade_at,
    }


async def recent_streak(session: AsyncSession, *, lookback_limit: int = 50) -> dict[str, Any]:
    """Length and kind of the current win-or-loss streak across recent trades.

    Returns `{"kind": "win"|"loss"|"none", "length": int}`. A streak ends when
    a trade with the opposite sign appears. Zero-PnL trades break the streak.
    """
    result = await session.execute(
        select(Trade).order_by(desc(Trade.exit_date)).limit(max(1, min(lookback_limit, 200)))
    )
    trades = list(result.scalars().all())
    if not trades:
        return {"kind": "none", "length": 0}

    first_kind = "win" if trades[0].net_profit > 0 else "loss" if trades[0].net_profit < 0 else "none"
    if first_kind == "none":
        return {"kind": "none", "length": 0}

    length = 0
    for t in trades:
        kind = "win" if t.net_profit > 0 else "loss" if t.net_profit < 0 else "none"
        if kind != first_kind:
            break
        length += 1
    return {"kind": first_kind, "length": length}
