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
