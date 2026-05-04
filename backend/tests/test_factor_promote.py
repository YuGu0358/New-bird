"""Tests for the periodic trajectory promotion path in factor_pipeline.

The promotion step:
  1. Reads up to 5 unscored trajectories (fitness IS NULL, evolution_step !=
     'crossover').
  2. Backtests each via factor_backtest_service.
  3. Writes fitness/ic_5d back to the trajectory row.
  4. If the result clears factor_vector_store.add_factor's gate, promotes the
     row to factor_records and links the trajectory's factor_record_id.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class _StubBacktestResult:
    def __init__(self, **kw):
        self.fitness = kw.get("fitness", 0.05)
        self.ic_1d = kw.get("ic_1d", 0.02)
        self.ic_5d = kw.get("ic_5d", 0.04)
        self.ic_20d = kw.get("ic_20d", 0.03)
        self.icir_5d = kw.get("icir_5d", 0.5)
        self.sharpe = kw.get("sharpe", 1.2)
        self.max_drawdown = kw.get("max_drawdown", 0.15)
        self.turnover = kw.get("turnover", 0.3)


class TrajectoryPromotionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._iso = await factor_test_isolation_setup(
            services=[
                "factor_pipeline",
                "factor_quanta_service",
                "factor_vector_store",
            ]
        )

    async def asyncTearDown(self):
        await factor_test_isolation_teardown(self._iso)

    async def test_promote_backtests_and_adds_passing_trajectory(self):
        from sqlalchemy import select

        from app.db.tables import FactorTrajectory
        from app.services import factor_pipeline as fp

        async with self._iso.session_factory() as s:
            s.add(
                FactorTrajectory(
                    research_direction="x",
                    math_intuition="y",
                    formula="rank(ts_mean(close,20))",
                    evolution_step="seed",
                )
            )
            await s.commit()

        with patch(
            "app.services.factor_backtest_service.backtest_factor",
            new=AsyncMock(return_value=_StubBacktestResult()),
        ), patch(
            "app.services.factor_vector_store.embed_formula",
            new=AsyncMock(return_value=None),
        ):
            promoted = await fp._promote_trajectories(generation=10)

        self.assertEqual(promoted, 1)
        async with self._iso.session_factory() as s:
            row = (await s.execute(select(FactorTrajectory))).scalar_one()
            self.assertIsNotNone(row.fitness)
            self.assertIsNotNone(row.factor_record_id)

    async def test_promote_skips_trajectories_already_scored(self):
        from app.db.tables import FactorTrajectory
        from app.services import factor_pipeline as fp

        async with self._iso.session_factory() as s:
            s.add(
                FactorTrajectory(
                    research_direction="x",
                    math_intuition="y",
                    formula="rank(ts_mean(close,20))",
                    evolution_step="seed",
                    fitness=0.05,  # already scored
                )
            )
            await s.commit()

        promoted = await fp._promote_trajectories(generation=10)
        self.assertEqual(promoted, 0)

    async def test_promote_handles_unparseable(self):
        from sqlalchemy import select

        from app.db.tables import FactorTrajectory
        from app.services import factor_pipeline as fp

        async with self._iso.session_factory() as s:
            s.add(
                FactorTrajectory(
                    research_direction="x",
                    math_intuition="y",
                    formula="not-a-formula!!",
                    evolution_step="seed",
                )
            )
            await s.commit()

        promoted = await fp._promote_trajectories(generation=10)
        self.assertEqual(promoted, 0)
        async with self._iso.session_factory() as s:
            row = (await s.execute(select(FactorTrajectory))).scalar_one()
            self.assertEqual(row.failure_reason, "unparseable")


if __name__ == "__main__":
    unittest.main()
