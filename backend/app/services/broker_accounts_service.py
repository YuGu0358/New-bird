"""CRUD service for the BrokerAccount table.

Every operation is async + takes an explicit `AsyncSession` so callers
can compose with their own transactions. Tier values are validated
against `core.broker.tiers.ALL_TIERS` — invalid tiers raise `ValueError`,
which the router translates to HTTP 400.

The (broker, account_id) pair is unique. Re-creating an existing pair
raises `ValueError` so callers can either update or surface the
conflict. We do NOT silently upsert because the alias and tier the
user typed are intentional and shouldn't be auto-overwritten.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import BrokerAccount
from core.broker.tiers import ALL_TIERS, TIER_2


def _normalize_broker(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_account_id(value: str) -> str:
    return str(value or "").strip()


def _serialize(row: BrokerAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker": row.broker,
        "account_id": row.account_id,
        "alias": row.alias,
        "tier": row.tier,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_accounts(
    session: AsyncSession, *, only_active: bool = False
) -> list[dict[str, Any]]:
    statement = select(BrokerAccount).order_by(BrokerAccount.id)
    if only_active:
        statement = statement.where(BrokerAccount.is_active.is_(True))
    result = await session.execute(statement)
    return [_serialize(row) for row in result.scalars().all()]


async def get_account(
    session: AsyncSession, account_pk: int
) -> dict[str, Any] | None:
    row = await session.get(BrokerAccount, account_pk)
    return _serialize(row) if row is not None else None


async def create_account(
    session: AsyncSession,
    *,
    broker: str,
    account_id: str,
    alias: str = "",
    tier: str = TIER_2,
) -> dict[str, Any]:
    broker_norm = _normalize_broker(broker)
    if not broker_norm:
        raise ValueError("broker is required")
    account_norm = _normalize_account_id(account_id)
    if not account_norm:
        raise ValueError("account_id is required")
    if tier not in ALL_TIERS:
        raise ValueError(f"tier must be one of {ALL_TIERS!r}")

    row = BrokerAccount(
        broker=broker_norm,
        account_id=account_norm,
        alias=str(alias or "").strip(),
        tier=tier,
        is_active=True,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ValueError(
            f"broker account already exists: {broker_norm}/{account_norm}"
        ) from exc
    await session.refresh(row)
    return _serialize(row)


async def update_alias(
    session: AsyncSession, account_pk: int, alias: str
) -> dict[str, Any] | None:
    row = await session.get(BrokerAccount, account_pk)
    if row is None:
        return None
    row.alias = str(alias or "").strip()
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def update_tier(
    session: AsyncSession, account_pk: int, tier: str
) -> dict[str, Any] | None:
    if tier not in ALL_TIERS:
        raise ValueError(f"tier must be one of {ALL_TIERS!r}")
    row = await session.get(BrokerAccount, account_pk)
    if row is None:
        return None
    row.tier = tier
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def set_active(
    session: AsyncSession, account_pk: int, *, is_active: bool
) -> dict[str, Any] | None:
    row = await session.get(BrokerAccount, account_pk)
    if row is None:
        return None
    row.is_active = is_active
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def delete_account(session: AsyncSession, account_pk: int) -> bool:
    row = await session.get(BrokerAccount, account_pk)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
