"""SQLAlchemy async engine, session factory, and base declarative class.

The DB file location is resolved from DATA_DIR env (preferred for deploys
with persistent volumes) or falls back to backend/trading_platform.db for
local dev.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

load_dotenv()

DATA_DIR = os.getenv("DATA_DIR", "").strip()
if DATA_DIR:
    DATABASE_FILE = Path(DATA_DIR).expanduser() / "trading_platform.db"
else:
    DATABASE_FILE = Path(__file__).resolve().parents[2] / "trading_platform.db"
DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATABASE_FILE}")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for async SQLAlchemy models."""


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_database() -> None:
    # Importing tables here ensures every ORM class is registered with
    # Base.metadata before create_all runs. Local import avoids the
    # circular: tables.py -> engine.py (for Base).
    from app.db import tables  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _apply_additive_migrations(connection)


async def _apply_additive_migrations(connection) -> None:
    """SQLite-friendly idempotent ADD-COLUMN migrations.

    `create_all` only creates missing tables; it never adds columns to
    existing ones. For schema additions on existing dev/prod DBs we
    inspect `PRAGMA table_info` and ADD COLUMN when the column is
    absent. Defaults backfill historical rows transparently.
    """
    from sqlalchemy import text

    # (table, column, ddl) — append rows here to land additive migrations.
    pending = [
        ("agent_analyses", "action_plan_json",
         "ALTER TABLE agent_analyses ADD COLUMN action_plan_json TEXT NOT NULL DEFAULT '{}'"),
    ]

    for table_name, column_name, ddl in pending:
        info = await connection.exec_driver_sql(f"PRAGMA table_info({table_name})")
        existing = {row[1] for row in info.fetchall()}  # row[1] is column name
        if column_name in existing:
            continue
        await connection.execute(text(ddl))
