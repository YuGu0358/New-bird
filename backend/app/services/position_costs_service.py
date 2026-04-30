"""CRUD service for position_costs.

A buy event recomputes avg_cost from the running aggregate; sells are
out of scope for the MVP (FIFO/LIFO accounting needs trade-by-trade
history we don't track here).

The `upsert` form lets the user import an existing position by setting
avg_cost + total_shares directly, bypassing the running-average math.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import PositionCost


def _serialize(row: PositionCost) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_account_id": row.broker_account_id,
        "ticker": row.ticker,
        "avg_cost_basis": float(row.avg_cost_basis),
        "total_shares": float(row.total_shares),
        "custom_stop_loss": (
            float(row.custom_stop_loss) if row.custom_stop_loss is not None else None
        ),
        "custom_take_profit": (
            float(row.custom_take_profit) if row.custom_take_profit is not None else None
        ),
        "notes": row.notes or "",
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_for_account(
    session: AsyncSession, *, broker_account_id: int
) -> list[dict[str, Any]]:
    stmt = (
        select(PositionCost)
        .where(PositionCost.broker_account_id == broker_account_id)
        .order_by(PositionCost.ticker)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


async def get_one(
    session: AsyncSession, *, broker_account_id: int, ticker: str
) -> Optional[dict[str, Any]]:
    stmt = select(PositionCost).where(
        PositionCost.broker_account_id == broker_account_id,
        PositionCost.ticker == ticker.upper(),
    )
    row = (await session.execute(stmt)).scalars().first()
    return _serialize(row) if row is not None else None


async def upsert(
    session: AsyncSession,
    *,
    broker_account_id: int,
    ticker: str,
    avg_cost_basis: float,
    total_shares: float,
    custom_stop_loss: Optional[float] = None,
    custom_take_profit: Optional[float] = None,
    notes: str = "",
) -> dict[str, Any]:
    """Direct upsert — replaces avg/shares wholesale (use record_buy for incremental)."""
    now = datetime.now(timezone.utc)
    stmt = sqlite_insert(PositionCost).values(
        broker_account_id=broker_account_id,
        ticker=ticker.upper(),
        avg_cost_basis=avg_cost_basis,
        total_shares=total_shares,
        custom_stop_loss=custom_stop_loss,
        custom_take_profit=custom_take_profit,
        notes=notes,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PositionCost.broker_account_id, PositionCost.ticker],
        set_={
            "avg_cost_basis": avg_cost_basis,
            "total_shares": total_shares,
            "custom_stop_loss": custom_stop_loss,
            "custom_take_profit": custom_take_profit,
            "notes": notes,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    await session.commit()
    fetched = await get_one(session, broker_account_id=broker_account_id, ticker=ticker)
    assert fetched is not None
    return fetched


async def record_buy(
    session: AsyncSession,
    *,
    broker_account_id: int,
    ticker: str,
    fill_price: float,
    fill_qty: float,
) -> dict[str, Any]:
    """Record a buy; recompute the running average cost basis."""
    if fill_price <= 0 or fill_qty <= 0:
        raise ValueError("fill_price and fill_qty must be positive")

    existing = await get_one(
        session, broker_account_id=broker_account_id, ticker=ticker
    )

    if existing is None:
        new_avg = fill_price
        new_shares = fill_qty
    else:
        old_total = existing["avg_cost_basis"] * existing["total_shares"]
        new_total_cost = old_total + fill_price * fill_qty
        new_shares = existing["total_shares"] + fill_qty
        new_avg = new_total_cost / new_shares if new_shares > 0 else 0.0

    return await upsert(
        session,
        broker_account_id=broker_account_id,
        ticker=ticker,
        avg_cost_basis=new_avg,
        total_shares=new_shares,
        custom_stop_loss=(existing or {}).get("custom_stop_loss"),
        custom_take_profit=(existing or {}).get("custom_take_profit"),
        notes=(existing or {}).get("notes", ""),
    )


async def delete(
    session: AsyncSession, *, broker_account_id: int, ticker: str
) -> bool:
    stmt = select(PositionCost).where(
        PositionCost.broker_account_id == broker_account_id,
        PositionCost.ticker == ticker.upper(),
    )
    row = (await session.execute(stmt)).scalars().first()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
