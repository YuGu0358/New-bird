"""Tests for the Factor Forge generation-history + population endpoints."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone

# Force DATA_DIR to a fresh tmp directory BEFORE app modules are imported so
# the test never touches the real ``trading_platform.db``.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="factor_history_endpoints_")
os.environ["DATA_DIR"] = _TEST_DATA_DIR


class FactorHistoryEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from sqlalchemy import delete

        from app.database import AsyncSessionLocal, init_database
        from app.db.tables import FactorGenerationStat, FactorPopulationState

        await init_database()
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FactorGenerationStat))
            await session.execute(delete(FactorPopulationState))
            await session.commit()

    async def test_history_returns_chronological(self) -> None:
        from fastapi.testclient import TestClient

        from app.database import AsyncSessionLocal
        from app.db.tables import FactorGenerationStat
        from app.main import app

        async with AsyncSessionLocal() as session:
            for gen, best in [(1, 0.01), (2, 0.03), (3, 0.05)]:
                session.add(
                    FactorGenerationStat(
                        generation=gen,
                        best_fitness=best,
                        median_fitness=0.0,
                        persisted_count=0,
                        evaluated_count=50,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
            await session.commit()

        client = TestClient(app)
        response = client.get("/api/factors/evolution/history?limit=10")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        self.assertEqual([i["generation"] for i in items], [1, 2, 3])

    async def test_history_limit_keeps_most_recent_oldest_first(self) -> None:
        from fastapi.testclient import TestClient

        from app.database import AsyncSessionLocal
        from app.db.tables import FactorGenerationStat
        from app.main import app

        async with AsyncSessionLocal() as session:
            for gen in range(1, 6):  # generations 1..5
                session.add(
                    FactorGenerationStat(
                        generation=gen,
                        best_fitness=float(gen) * 0.01,
                        median_fitness=0.0,
                        persisted_count=0,
                        evaluated_count=10,
                        completed_at=datetime.now(timezone.utc),
                    )
                )
            await session.commit()

        client = TestClient(app)
        response = client.get("/api/factors/evolution/history?limit=3")
        self.assertEqual(response.status_code, 200)
        items = response.json()["items"]
        # Most-recent 3 (3,4,5) returned in chronological order.
        self.assertEqual([i["generation"] for i in items], [3, 4, 5])

    async def test_population_returns_slots(self) -> None:
        from fastapi.testclient import TestClient

        from app.database import AsyncSessionLocal
        from app.db.tables import FactorPopulationState
        from app.main import app

        async with AsyncSessionLocal() as session:
            for slot in range(3):
                session.add(
                    FactorPopulationState(
                        slot=slot,
                        formula="rank(close)",
                        fitness=0.02 + slot * 0.01,
                        generation=7,
                    )
                )
            await session.commit()

        client = TestClient(app)
        response = client.get("/api/factors/evolution/population")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["generation"], 7)
        self.assertEqual(len(body["slots"]), 3)
        self.assertAlmostEqual(body["slots"][0]["fitness"], 0.02, places=3)

    async def test_population_empty_returns_zero_generation(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)
        response = client.get("/api/factors/evolution/population")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["generation"], 0)
        self.assertEqual(body["slots"], [])


if __name__ == "__main__":
    unittest.main()
