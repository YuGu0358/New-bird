"""Unit tests for `factor_news_service`.

All network calls (Tavily, OpenAI) are mocked. The tests exercise the
fetch-shape adaptation, the idempotent upsert path, and the sentiment-parsing
fallback for chatty model output.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, patch


class FactorNewsServiceTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        os.environ["DATA_DIR"] = cls._tmp_dir.name

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_dir.cleanup()
        os.environ.pop("DATA_DIR", None)

    async def asyncSetUp(self) -> None:
        db_path = Path(self._tmp_dir.name) / f"news_{id(self)}.db"
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

        from app.services import factor_news_service as svc

        self._svc_patch = patch.object(svc, "AsyncSessionLocal", self._session_factory)
        self._svc_patch.start()

        from app.db.engine import Base
        from app.db import tables  # noqa: F401

        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        self._svc_patch.stop()
        for p in self._patches:
            p.stop()
        await self._engine.dispose()

    async def test_update_news_features_persists_row(self) -> None:
        import json

        from sqlalchemy import select

        from app.db.tables import DailyNewsFeatures
        from app.services import factor_news_service as svc

        target = date(2026, 4, 30)
        headlines = ["AAPL beats Q2 estimates", "iPhone sales jump"]
        with patch.object(
            svc,
            "_fetch_headlines_for",
            new=AsyncMock(return_value=headlines),
        ), patch.object(svc, "_score_sentiment_sync", return_value=0.7):
            n = await svc.update_news_features(["AAPL"], target)

        self.assertEqual(n, 1)
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(DailyNewsFeatures).where(DailyNewsFeatures.symbol == "AAPL")
                )
            ).scalar_one()
            self.assertAlmostEqual(row.sentiment, 0.7)
            self.assertEqual(row.news_count, 2)
            self.assertEqual(json.loads(row.headlines), headlines)

    async def test_update_news_features_is_idempotent(self) -> None:
        from sqlalchemy import func, select

        from app.db.tables import DailyNewsFeatures
        from app.services import factor_news_service as svc

        target = date(2026, 4, 30)
        with patch.object(
            svc, "_fetch_headlines_for", new=AsyncMock(return_value=["initial"])
        ), patch.object(svc, "_score_sentiment_sync", return_value=0.1):
            await svc.update_news_features(["AAPL"], target)

        with patch.object(
            svc, "_fetch_headlines_for", new=AsyncMock(return_value=["updated", "twice"])
        ), patch.object(svc, "_score_sentiment_sync", return_value=-0.4):
            await svc.update_news_features(["AAPL"], target)

        async with self._session_factory() as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(DailyNewsFeatures)
                )
            ).scalar_one()
            row = (
                await session.execute(
                    select(DailyNewsFeatures).where(DailyNewsFeatures.symbol == "AAPL")
                )
            ).scalar_one()
        self.assertEqual(count, 1)
        self.assertAlmostEqual(row.sentiment, -0.4)
        self.assertEqual(row.news_count, 2)

    async def test_fetch_headlines_uses_tavily_payload_shape(self) -> None:
        from app.services import factor_news_service as svc

        payload = {
            "headlines": [
                {"title": "Headline 1"},
                {"title": "Headline 2"},
                {"title": ""},
                {"headline": "Headline 4"},
            ]
        }
        with patch.object(
            svc.tavily_service,
            "fetch_raw_headlines",
            new=AsyncMock(return_value=payload),
        ):
            result = await svc._fetch_headlines_for("AAPL", date(2026, 4, 30))

        self.assertEqual(result, ["Headline 1", "Headline 2", "Headline 4"])

    async def test_fetch_headlines_swallows_tavily_errors(self) -> None:
        from app.services import factor_news_service as svc

        async def boom(*args, **kwargs):
            raise RuntimeError("tavily down")

        with patch.object(svc.tavily_service, "fetch_raw_headlines", new=boom):
            result = await svc._fetch_headlines_for("AAPL", date(2026, 4, 30))
        self.assertEqual(result, [])

    def test_parse_sentiment_handles_chatty_response(self) -> None:
        from app.services.factor_news_service import _parse_sentiment

        self.assertAlmostEqual(_parse_sentiment("0.42"), 0.42)
        self.assertAlmostEqual(_parse_sentiment("score: -0.3 strongly bearish"), -0.3)
        self.assertEqual(_parse_sentiment(""), 0.0)
        self.assertEqual(_parse_sentiment("nonsense"), 0.0)
        # clamped to [-1, 1]
        self.assertEqual(_parse_sentiment("2.5"), 1.0)
        self.assertEqual(_parse_sentiment("-3"), -1.0)

    def test_score_sentiment_short_circuits_on_empty_headlines(self) -> None:
        from app.services.factor_news_service import _score_sentiment_sync

        # Should NOT touch OpenAI when headlines are empty.
        with patch("app.services.factor_news_service.create_client") as factory:
            value = _score_sentiment_sync([])
        self.assertEqual(value, 0.0)
        factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
