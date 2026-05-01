"""Unit tests for `factor_meta_service`.

Network calls (yfinance) are patched; only the upsert + freshness logic is
exercised against an isolated SQLite DB.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


class FactorMetaServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = cls._tmp_dir.name

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_dir.cleanup()
        os.environ.pop("DATA_DIR", None)

    async def asyncSetUp(self) -> None:
        # Re-bind the engine to a fresh per-test DB file so state doesn't leak
        # across tests (DDL is cheap on aiosqlite).
        db_path = Path(self._tmp_dir.name) / f"meta_{id(self)}.db"
        if db_path.exists():
            db_path.unlink()
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        from app.db import engine as engine_module

        self._engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
        )
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        self._patches = [
            patch.object(engine_module, "engine", self._engine),
            patch.object(engine_module, "AsyncSessionLocal", self._session_factory),
        ]
        for p in self._patches:
            p.start()

        # Patch the names re-exported into the service module too.
        from app.services import factor_meta_service as svc

        self._svc_patch = patch.object(svc, "AsyncSessionLocal", self._session_factory)
        self._svc_patch.start()

        from app.db.engine import Base
        from app.db import tables  # noqa: F401  (register ORM tables)

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        self._svc_patch.stop()
        for p in self._patches:
            p.stop()
        await self._engine.dispose()

    async def test_refresh_inserts_new_rows(self) -> None:
        from sqlalchemy import select

        from app.db.tables import SymbolMeta
        from app.services import factor_meta_service as svc

        with patch.object(
            svc,
            "_fetch_meta_sync",
            return_value={
                "symbol": "AAPL",
                "sector": "Tech",
                "industry": "Hardware",
                "market_cap": 3.0e12,
            },
        ):
            n = await svc.refresh_symbol_meta(["AAPL"])

        self.assertEqual(n, 1)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(SymbolMeta).where(SymbolMeta.symbol == "AAPL")
                )
            ).scalar_one()
            self.assertEqual(row.sector, "Tech")
            self.assertEqual(row.industry, "Hardware")
            self.assertAlmostEqual(row.market_cap, 3.0e12)

    async def test_refresh_skips_fresh_records(self) -> None:
        from app.db.tables import SymbolMeta
        from app.services import factor_meta_service as svc

        async with self._session_factory() as session:
            session.add(
                SymbolMeta(
                    symbol="MSFT",
                    sector="Tech",
                    refreshed_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()

        with patch.object(svc, "_fetch_meta_sync") as fetch:
            n = await svc.refresh_symbol_meta(["MSFT"])

        self.assertEqual(n, 0)
        fetch.assert_not_called()

    async def test_refresh_updates_stale_record(self) -> None:
        from datetime import timedelta

        from sqlalchemy import select

        from app.db.tables import SymbolMeta
        from app.services import factor_meta_service as svc

        async with self._session_factory() as session:
            session.add(
                SymbolMeta(
                    symbol="GOOG",
                    sector="OldSector",
                    industry="OldIndustry",
                    market_cap=1.0e9,
                    refreshed_at=datetime.now(timezone.utc) - timedelta(days=30),
                )
            )
            await session.commit()

        with patch.object(
            svc,
            "_fetch_meta_sync",
            return_value={
                "symbol": "GOOG",
                "sector": "Communication Services",
                "industry": "Internet Content",
                "market_cap": 2.0e12,
            },
        ):
            n = await svc.refresh_symbol_meta(["GOOG"])

        self.assertEqual(n, 1)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(SymbolMeta).where(SymbolMeta.symbol == "GOOG")
                )
            ).scalar_one()
            self.assertEqual(row.sector, "Communication Services")
            self.assertAlmostEqual(row.market_cap, 2.0e12)

    async def test_refresh_handles_fetch_failure(self) -> None:
        from app.services import factor_meta_service as svc

        with patch.object(svc, "_fetch_meta_sync", return_value=None):
            n = await svc.refresh_symbol_meta(["NVDA"])
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
