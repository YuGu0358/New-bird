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

    def test_evolution_status_endpoint(self) -> None:
        from fastapi.testclient import TestClient

        from app.main import app
        from app.services import factor_pipeline

        fake_status = {
            "is_running": True,
            "current_generation": 12,
            "best_fitness_recent": 0.054,
            "last_generation_completed_at": None,
            "population_size": 50,
            "library_count": 7,
            "error": None,
        }
        with patch.object(
            factor_pipeline, "evolution_status", new=AsyncMock(return_value=fake_status)
        ):
            client = TestClient(app)
            response = client.get("/api/factors/evolution/status")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["current_generation"], 12)
        self.assertTrue(body["is_running"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
