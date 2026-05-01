"""Tests for the Factor Forge router and pipeline orchestration.

The pipeline is mocked at the service boundary — these tests never touch
yfinance, Alpaca, OpenAI, Tavily, or the GP loop.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch


class FactorRouterTests(unittest.IsolatedAsyncioTestCase):
    def test_library_endpoint_returns_records(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import factor_vector_store

        sample = [
            {
                "id": 1,
                "formula": "rank(close)",
                "fitness": 0.05,
                "ic_1d": 0.01,
                "ic_5d": 0.02,
                "ic_20d": 0.03,
                "icir": 0.4,
                "sharpe": 1.1,
                "max_drawdown": -0.12,
                "turnover": 0.3,
                "generation": 1,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        ]

        with patch.object(
            factor_vector_store, "list_factors", new=AsyncMock(return_value=sample)
        ):
            client = TestClient(app)
            response = client.get("/api/factors/library?limit=10")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["items"][0]["formula"], "rank(close)")
        self.assertEqual(body["items"][0]["generation"], 1)

    def test_run_evolution_queues_background_task(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.routers import factors as factors_router
        from app.services import factor_pipeline

        with patch.object(
            factor_pipeline, "_create_run", new=AsyncMock(return_value=99)
        ), patch.object(
            factors_router,
            "_runner_then_finish",
            new=AsyncMock(return_value=None),
        ):
            client = TestClient(app)
            response = client.post("/api/factors/run-evolution")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["run_id"], 99)
        self.assertEqual(body["status"], "queued")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
