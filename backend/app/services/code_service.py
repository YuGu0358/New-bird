"""User strategy code service — persistence + sandbox loading orchestration.

This is the only module that ties the AST validator + sandbox loader to
the DB layer. The router calls these functions; everything else stays
pure.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import UserStrategy
from core.code_loader import (
    SandboxLoadError,
    load_strategy_from_source,
    unregister_strategy,
)

logger = logging.getLogger(__name__)


class CodeServiceError(RuntimeError):
    """Wraps validation/sandbox/db errors for the router."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def list_user_strategies(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(UserStrategy).order_by(desc(UserStrategy.id)))
    ).scalars().all()
    return [_serialize(row) for row in rows]


async def get_user_strategy(
    session: AsyncSession, strategy_id: int
) -> Optional[dict[str, Any]]:
    row = await session.get(UserStrategy, strategy_id)
    if row is None:
        return None
    return _serialize(row, include_source=True)


async def save_user_strategy(
    session: AsyncSession,
    *,
    slot_name: str,
    display_name: str,
    description: str,
    source_code: str,
) -> dict[str, Any]:
    """Validate → load → persist. If a row with the same slot_name exists,
    we treat this as an update: unregister the old class first, then load
    the new one.
    """
    if not slot_name.strip():
        raise CodeServiceError("slot_name is required")
    slot_name = slot_name.strip()

    existing = (
        await session.execute(
            select(UserStrategy).where(UserStrategy.slot_name == slot_name)
        )
    ).scalar_one_or_none()

    if existing is not None:
        # Hot-reload: drop old class so re-registration succeeds.
        unregister_strategy(slot_name)

    try:
        load_strategy_from_source(source_code, expected_name=slot_name)
    except SandboxLoadError as exc:
        if existing is not None:
            existing.status = "failed"
            existing.last_error = str(exc)
            existing.updated_at = datetime.now(timezone.utc)
            await session.commit()
        raise CodeServiceError(str(exc)) from exc

    if existing is None:
        row = UserStrategy(
            slot_name=slot_name,
            display_name=display_name,
            description=description,
            source_code=source_code,
            status="active",
            last_error="",
        )
        session.add(row)
    else:
        existing.display_name = display_name
        existing.description = description
        existing.source_code = source_code
        existing.status = "active"
        existing.last_error = ""
        existing.updated_at = datetime.now(timezone.utc)
        row = existing

    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def reload_user_strategy(
    session: AsyncSession, strategy_id: int
) -> dict[str, Any]:
    """Re-validate + re-register a stored strategy without changing its source."""
    row = await session.get(UserStrategy, strategy_id)
    if row is None:
        raise CodeServiceError(f"User strategy {strategy_id} not found")

    unregister_strategy(row.slot_name)
    try:
        load_strategy_from_source(row.source_code, expected_name=row.slot_name)
    except SandboxLoadError as exc:
        row.status = "failed"
        row.last_error = str(exc)
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()
        raise CodeServiceError(str(exc)) from exc

    row.status = "active"
    row.last_error = ""
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def delete_user_strategy(
    session: AsyncSession, strategy_id: int
) -> bool:
    row = await session.get(UserStrategy, strategy_id)
    if row is None:
        return False
    unregister_strategy(row.slot_name)
    await session.delete(row)
    await session.commit()
    return True


async def reload_all_user_strategies(session: AsyncSession) -> dict[str, Any]:
    """Called on app startup. Walks every "active" row and re-registers it.
    Failures are logged + the row is marked "failed" but never blocks boot.
    """
    rows = (
        await session.execute(
            select(UserStrategy).where(UserStrategy.status != "disabled")
        )
    ).scalars().all()

    succeeded = 0
    failed: list[dict[str, str]] = []
    for row in rows:
        unregister_strategy(row.slot_name)
        try:
            load_strategy_from_source(row.source_code, expected_name=row.slot_name)
            row.status = "active"
            row.last_error = ""
            succeeded += 1
        except SandboxLoadError as exc:
            row.status = "failed"
            row.last_error = str(exc)
            failed.append({"slot_name": row.slot_name, "error": str(exc)})
            logger.warning("Failed to reload user strategy %s: %s", row.slot_name, exc)
    await session.commit()
    return {"loaded": succeeded, "failed": failed}


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def _serialize(row: UserStrategy, *, include_source: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": row.id,
        "slot_name": row.slot_name,
        "display_name": row.display_name,
        "description": row.description,
        "status": row.status,
        "last_error": row.last_error,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if include_source:
        payload["source_code"] = row.source_code
    return payload
