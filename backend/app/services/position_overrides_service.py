"""CRUD service for the PositionOverride table.

Upsert semantics: `set_override(broker_account_id, ticker, **fields)`
either creates or updates the row; partial updates are supported via
the _UNSET sentinel (omitted fields keep their previous value, but
the API layer cannot distinguish "absent" vs "explicitly null" so
clients use the GET-modify-PUT pattern for partial writes).

Validation:
- broker_account_id MUST reference an existing BrokerAccount (we check
  with a `session.get` lookup). Service raises `ValueError` on miss;
  router translates to 400.
- ticker is normalized to uppercase trimmed.
- tier_override, when provided, must be one of `core.broker.tiers.ALL_TIERS`
  or None.
- Numeric prices, when provided, must be finite + non-negative; None
  clears the field.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import BrokerAccount, PositionOverride
from core.broker.tiers import ALL_TIERS


_UNSET = object()


def _normalize_ticker(value: str) -> str:
    out = str(value or "").strip().upper()
    if not out:
        raise ValueError("ticker is required")
    return out


def _validate_price(name: str, value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    if float(value) < 0:
        raise ValueError(f"{name} must be >= 0")
    return float(value)


def _validate_tier_override(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ALL_TIERS:
        raise ValueError(f"tier_override must be one of {ALL_TIERS!r} or null")
    return value


def _serialize(row: PositionOverride) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_account_id": row.broker_account_id,
        "ticker": row.ticker,
        "stop_price": row.stop_price,
        "take_profit_price": row.take_profit_price,
        "notes": row.notes,
        "tier_override": row.tier_override,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_overrides(
    session: AsyncSession,
    *,
    broker_account_id: int | None = None,
    ticker: str | None = None,
) -> list[dict[str, Any]]:
    statement = select(PositionOverride).order_by(PositionOverride.id)
    if broker_account_id is not None:
        statement = statement.where(
            PositionOverride.broker_account_id == broker_account_id
        )
    if ticker is not None:
        statement = statement.where(
            PositionOverride.ticker == _normalize_ticker(ticker)
        )
    result = await session.execute(statement)
    return [_serialize(row) for row in result.scalars().all()]


async def get_override(
    session: AsyncSession,
    broker_account_id: int,
    ticker: str,
) -> dict[str, Any] | None:
    ticker_norm = _normalize_ticker(ticker)
    statement = select(PositionOverride).where(
        PositionOverride.broker_account_id == broker_account_id,
        PositionOverride.ticker == ticker_norm,
    )
    result = await session.execute(statement)
    row = result.scalars().first()
    return _serialize(row) if row is not None else None


async def set_override(
    session: AsyncSession,
    *,
    broker_account_id: int,
    ticker: str,
    stop_price: float | None | object = _UNSET,
    take_profit_price: float | None | object = _UNSET,
    notes: str | None | object = _UNSET,
    tier_override: str | None | object = _UNSET,
) -> dict[str, Any]:
    """Upsert. Fields left as `_UNSET` are unchanged on update; on insert
    they default to None. Explicitly passing None CLEARS the field.

    Verifies broker_account_id exists. Raises ValueError on validation
    failure or unknown broker account.
    """
    ticker_norm = _normalize_ticker(ticker)

    account = await session.get(BrokerAccount, broker_account_id)
    if account is None:
        raise ValueError(
            f"broker_account_id {broker_account_id} does not exist"
        )

    if stop_price is not _UNSET:
        stop_price = _validate_price("stop_price", stop_price)  # type: ignore[arg-type]
    if take_profit_price is not _UNSET:
        take_profit_price = _validate_price(
            "take_profit_price", take_profit_price  # type: ignore[arg-type]
        )
    if tier_override is not _UNSET:
        tier_override = _validate_tier_override(tier_override)  # type: ignore[arg-type]

    statement = select(PositionOverride).where(
        PositionOverride.broker_account_id == broker_account_id,
        PositionOverride.ticker == ticker_norm,
    )
    result = await session.execute(statement)
    row = result.scalars().first()

    now = datetime.now(timezone.utc)
    if row is None:
        row = PositionOverride(
            broker_account_id=broker_account_id,
            ticker=ticker_norm,
            stop_price=None if stop_price is _UNSET else stop_price,  # type: ignore[arg-type]
            take_profit_price=(
                None if take_profit_price is _UNSET else take_profit_price  # type: ignore[arg-type]
            ),
            notes=None if notes is _UNSET else notes,  # type: ignore[arg-type]
            tier_override=(
                None if tier_override is _UNSET else tier_override  # type: ignore[arg-type]
            ),
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        if stop_price is not _UNSET:
            row.stop_price = stop_price  # type: ignore[assignment]
        if take_profit_price is not _UNSET:
            row.take_profit_price = take_profit_price  # type: ignore[assignment]
        if notes is not _UNSET:
            row.notes = notes  # type: ignore[assignment]
        if tier_override is not _UNSET:
            row.tier_override = tier_override  # type: ignore[assignment]
        row.updated_at = now

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(
            f"position override already exists for {broker_account_id}/{ticker_norm}"
        ) from exc
    await session.refresh(row)
    return _serialize(row)


async def delete_override(
    session: AsyncSession,
    broker_account_id: int,
    ticker: str,
) -> bool:
    ticker_norm = _normalize_ticker(ticker)
    statement = select(PositionOverride).where(
        PositionOverride.broker_account_id == broker_account_id,
        PositionOverride.ticker == ticker_norm,
    )
    result = await session.execute(statement)
    row = result.scalars().first()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
