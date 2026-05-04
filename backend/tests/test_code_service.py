"""User strategy code service: persist + reload round-trip."""
from __future__ import annotations

import pytest

from app.database import AsyncSessionLocal, UserStrategy
from core.strategy.registry import default_registry


_VALID = '''\
from __future__ import annotations
from datetime import datetime

from core.strategy import Strategy, register_strategy
from app.models import StrategyExecutionParameters


@register_strategy("__test_userstrat_save")
class _SaveTest(Strategy):
    description = "save round-trip test"

    @classmethod
    def parameters_schema(cls):
        return StrategyExecutionParameters

    def __init__(self, parameters, *, broker=None) -> None:
        super().__init__(parameters)
        self._broker = broker

    def universe(self) -> list[str]:
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx) -> None:
        return None

    async def on_periodic_sync(self, ctx, now: datetime) -> None:
        return None

    async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
        return None
'''


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Each test runs against a fresh tmp DB."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "code.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", factory)
    AsyncSessionLocal.configure(bind=new_engine)
    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    # cleanup test-prefixed registry entries
    for name in list(default_registry.list_names()):
        if name.startswith("__test_"):
            default_registry._strategies.pop(name, None)
    await new_engine.dispose()


@pytest.mark.asyncio
async def test_save_user_strategy_persists_and_registers() -> None:
    from app.services import code_service

    async with AsyncSessionLocal() as session:
        result = await code_service.save_user_strategy(
            session,
            slot_name="__test_userstrat_save",
            display_name="Save test",
            description="round-trip",
            source_code=_VALID,
        )
        assert result["status"] == "active"
        assert result["slot_name"] == "__test_userstrat_save"

    # Registered in registry
    cls = default_registry.get("__test_userstrat_save")
    assert cls.description == "save round-trip test"


@pytest.mark.asyncio
async def test_save_user_strategy_rejects_bad_code() -> None:
    from app.services import code_service

    bad = "import os\n" + _VALID
    async with AsyncSessionLocal() as session:
        with pytest.raises(code_service.CodeServiceError, match="forbidden import"):
            await code_service.save_user_strategy(
                session,
                slot_name="__test_userstrat_bad",
                display_name="Bad",
                description="",
                source_code=bad,
            )


@pytest.mark.asyncio
async def test_save_then_update_overwrites() -> None:
    from app.services import code_service

    async with AsyncSessionLocal() as session:
        await code_service.save_user_strategy(
            session,
            slot_name="__test_userstrat_save",
            display_name="v1",
            description="first",
            source_code=_VALID,
        )
        # Save again under same slot — should update, not create a duplicate.
        result = await code_service.save_user_strategy(
            session,
            slot_name="__test_userstrat_save",
            display_name="v2",
            description="second",
            source_code=_VALID,
        )
        assert result["display_name"] == "v2"

        from sqlalchemy import select
        rows = (await session.execute(select(UserStrategy))).scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_delete_user_strategy_unregisters() -> None:
    from app.services import code_service

    async with AsyncSessionLocal() as session:
        result = await code_service.save_user_strategy(
            session,
            slot_name="__test_userstrat_save",
            display_name="x",
            description="",
            source_code=_VALID,
        )
        deleted = await code_service.delete_user_strategy(session, result["id"])
        assert deleted is True
        assert "__test_userstrat_save" not in default_registry.list_names()


@pytest.mark.asyncio
async def test_reload_all_user_strategies_recovers_active_rows() -> None:
    from app.services import code_service

    async with AsyncSessionLocal() as session:
        await code_service.save_user_strategy(
            session,
            slot_name="__test_userstrat_save",
            display_name="x",
            description="",
            source_code=_VALID,
        )

    # Wipe the registry to simulate a process restart.
    for name in list(default_registry.list_names()):
        if name.startswith("__test_"):
            default_registry._strategies.pop(name, None)

    async with AsyncSessionLocal() as session:
        report = await code_service.reload_all_user_strategies(session)
        assert report["loaded"] >= 1
        assert "__test_userstrat_save" in default_registry.list_names()
