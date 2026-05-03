"""Tests for the continuous Factor Forge evolution loop."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

# Force DATA_DIR to a fresh tmp directory BEFORE app modules are imported so
# the test never touches the real ``trading_platform.db`` (which may be held
# open by a running dev server).
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="factor_pipeline_loop_")
os.environ["DATA_DIR"] = _TEST_DATA_DIR


class FactorPipelineLoopTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from app.database import init_database

        await init_database()
        # Reset module-level singleton state so tests don't see leftovers.
        from app.services import factor_pipeline

        await factor_pipeline._save_singleton(
            current_generation=0,
            best_fitness_recent=None,
            last_generation_completed_at=None,
            last_error=None,
        )

    async def test_start_then_stop_loop(self) -> None:
        from app.services import factor_pipeline

        async def fake_one_gen(pop, **kwargs):  # noqa: ANN001, ARG001
            return pop, [0.05] * len(pop), 0.05

        with patch.object(factor_pipeline, "_run_one_generation", new=fake_one_gen):
            msg = await factor_pipeline.start_loop()
            self.assertIn(msg, ("started", "already running"))
            await asyncio.sleep(0.1)  # let it tick once
            stop_msg = await factor_pipeline.stop_loop(timeout=2.0)
            self.assertEqual(stop_msg, "stopped")

    async def test_status_reflects_singleton(self) -> None:
        from app.services import factor_pipeline

        await factor_pipeline._save_singleton(
            current_generation=42,
            best_fitness_recent=0.067,
        )
        status = await factor_pipeline.evolution_status()
        self.assertEqual(status["current_generation"], 42)
        self.assertAlmostEqual(status["best_fitness_recent"], 0.067, places=3)
        self.assertIn("is_running", status)
        self.assertIn("population_size", status)
        self.assertIn("library_count", status)

    async def test_seeded_population_no_random_garbage(self) -> None:
        import random

        from app.services.factor_pipeline import _seeded_population
        from core.factors.ast import serialize
        from core.factors.seeds import get_seed_population

        seeds = {serialize(s) for s in get_seed_population()}
        pop = _seeded_population(random.Random(42), 50)
        self.assertEqual(len(pop), 50)

        # First 60% should be exact seeds.
        first_30 = pop[:30]
        for f in first_30:
            self.assertIn(serialize(f), seeds)

    async def test_stop_loop_when_not_running(self) -> None:
        from app.services import factor_pipeline

        # Ensure stopped first.
        await factor_pipeline.stop_loop(timeout=1.0)
        msg = await factor_pipeline.stop_loop(timeout=1.0)
        self.assertEqual(msg, "not running")


if __name__ == "__main__":
    unittest.main()
