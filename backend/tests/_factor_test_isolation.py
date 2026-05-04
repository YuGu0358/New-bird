"""Per-test SQLite isolation helper for factor-suite tests.

Usage::

    class MyTests(unittest.IsolatedAsyncioTestCase):
        async def asyncSetUp(self):
            self._iso = await factor_test_isolation_setup(
                services=["factor_vector_store", "factor_pipeline"]
            )

        async def asyncTearDown(self):
            await factor_test_isolation_teardown(self._iso)

The shared production ``trading_platform.db`` is left untouched; each test
gets a fresh in-memory-grade SQLite file under a tempdir.
"""
from __future__ import annotations

import importlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@dataclass
class _Isolation:
    tmp_dir: tempfile.TemporaryDirectory
    engine: Any
    session_factory: Any
    patches: list = field(default_factory=list)


async def factor_test_isolation_setup(services: list[str]) -> _Isolation:
    """Build a fresh per-test SQLite + patch the listed service modules.

    ``services`` are import-path tail names like ``"factor_vector_store"`` —
    we resolve them under ``app.services`` and patch their module-level
    ``AsyncSessionLocal`` reference.
    """
    tmp_dir = tempfile.TemporaryDirectory()
    db_path = Path(tmp_dir.name) / f"factor_test_{id(tmp_dir)}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    sf = async_sessionmaker(engine, expire_on_commit=False)

    patches = []
    for svc_name in services:
        module = importlib.import_module(f"app.services.{svc_name}")
        # Only patch modules that actually imported AsyncSessionLocal at module load —
        # services that delegate DB I/O to other services don't need patching here.
        if hasattr(module, "AsyncSessionLocal"):
            patches.append(patch.object(module, "AsyncSessionLocal", sf))
    for p in patches:
        p.start()

    from app.db.engine import Base
    from app.db import tables  # noqa: F401 — register ORM models
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    return _Isolation(tmp_dir=tmp_dir, engine=engine, session_factory=sf, patches=patches)


async def factor_test_isolation_teardown(iso: _Isolation) -> None:
    for p in iso.patches:
        p.stop()
    await iso.engine.dispose()
    iso.tmp_dir.cleanup()
