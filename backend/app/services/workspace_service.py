"""CRUD service for the UserWorkspace table (Phase 7.3).

The DB stores `state_json` as a TEXT blob; this layer transparently
encodes/decodes via `json.dumps` / `json.loads` so callers work with
plain dicts.

Upsert by name: PUT replaces the entire `state` blob if a row with the
same name exists, else inserts a new row.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tables import UserWorkspace


def _serialize(row: UserWorkspace) -> dict[str, Any]:
    """Build a dict shaped for `WorkspaceView` (state decoded from JSON)."""
    try:
        state = json.loads(row.state_json) if row.state_json else {}
    except json.JSONDecodeError:
        # Defensive: a corrupt blob shouldn't 500 the whole list endpoint.
        state = {}
    return {
        "id": row.id,
        "name": row.name,
        "state": state,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def list_workspaces(session: AsyncSession) -> list[dict[str, Any]]:
    """Return all saved workspaces, ordered by name (stable for the UI)."""
    statement = select(UserWorkspace).order_by(UserWorkspace.name)
    result = await session.execute(statement)
    return [_serialize(row) for row in result.scalars().all()]


async def get_workspace(
    session: AsyncSession, name: str
) -> dict[str, Any] | None:
    """Lookup by exact name. Returns None when not found."""
    statement = select(UserWorkspace).where(UserWorkspace.name == name)
    result = await session.execute(statement)
    row = result.scalars().first()
    return _serialize(row) if row is not None else None


async def upsert_workspace(
    session: AsyncSession, name: str, state: dict[str, Any]
) -> dict[str, Any]:
    """Insert or replace the workspace row keyed by `name`.

    Uses SQLite's `INSERT ... ON CONFLICT(name) DO UPDATE` so two concurrent
    PUTs with the same name converge cleanly instead of one of them blowing
    up on the unique constraint (TOCTOU-safe).

    On update the `state_json` is fully overwritten and `updated_at`
    bumped. On insert both timestamps are set to now.
    """
    encoded = json.dumps(state)
    now = datetime.now(timezone.utc)

    stmt = sqlite_insert(UserWorkspace).values(
        name=name,
        state_json=encoded,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[UserWorkspace.name],
        set_={
            "state_json": encoded,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    await session.commit()

    # Re-read the canonical row so callers see the persisted timestamps
    # (created_at on update is unchanged from the original insert).
    fetch = await session.execute(
        select(UserWorkspace).where(UserWorkspace.name == name)
    )
    row = fetch.scalars().one()
    return _serialize(row)


async def delete_workspace(session: AsyncSession, name: str) -> bool:
    """Delete by name. Returns True if a row was removed, False if absent."""
    statement = select(UserWorkspace).where(UserWorkspace.name == name)
    result = await session.execute(statement)
    row = result.scalars().first()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True
