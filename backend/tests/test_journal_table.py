"""Round-trip persistence test for the JournalEntry ORM table."""
from __future__ import annotations

import pytest

from app.database import AsyncSessionLocal, JournalEntry


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so JournalEntry rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "journal.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


@pytest.mark.asyncio
async def test_journal_entry_round_trip() -> None:
    async with AsyncSessionLocal() as session:
        entry = JournalEntry(
            title="Test",
            body="hello",
            symbols=["NVDA", "TSLA"],
            mood="bullish",
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)

        assert entry.id > 0
        assert entry.title == "Test"
        assert entry.body == "hello"
        assert entry.symbols == ["NVDA", "TSLA"]
        assert entry.mood == "bullish"
        assert entry.created_at is not None
        assert entry.updated_at is not None
        # updated_at and created_at come from two separate datetime.now() calls,
        # but on first insert they should be within a second of each other.
        assert abs((entry.updated_at - entry.created_at).total_seconds()) < 1
