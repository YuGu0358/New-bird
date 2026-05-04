"""Tests for the PCA-2D factor landscape projection service."""
from __future__ import annotations

import unittest

import numpy as np

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class FactorLandscapeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._iso = await factor_test_isolation_setup(
            services=["factor_landscape_service"]
        )

    async def asyncTearDown(self) -> None:
        await factor_test_isolation_teardown(self._iso)

    async def test_landscape_returns_empty_when_no_records(self) -> None:
        from app.services.factor_landscape_service import compute_landscape

        result = await compute_landscape()
        self.assertEqual(result, [])

    async def test_landscape_projects_two_factors_to_2d(self) -> None:
        from app.db.tables import FactorRecord
        from app.services.factor_landscape_service import compute_landscape

        e1 = np.random.RandomState(0).randn(1536).astype(np.float32).tobytes()
        e2 = np.random.RandomState(1).randn(1536).astype(np.float32).tobytes()
        async with self._iso.session_factory() as s:
            s.add(
                FactorRecord(
                    formula="rank(close)", fitness=0.05, formula_embedding=e1
                )
            )
            s.add(
                FactorRecord(
                    formula="rank(volume)", fitness=0.03, formula_embedding=e2
                )
            )
            await s.commit()

        result = await compute_landscape(limit=10)
        self.assertEqual(len(result), 2)
        for p in result:
            self.assertIn("x", p)
            self.assertIn("y", p)
            self.assertIsInstance(p["x"], float)
            self.assertIsInstance(p["y"], float)

    async def test_landscape_skips_records_with_zero_embedding(self) -> None:
        from app.db.tables import FactorRecord
        from app.services.factor_landscape_service import compute_landscape

        zero = np.zeros(1536, dtype=np.float32).tobytes()
        nonzero = np.random.RandomState(2).randn(1536).astype(np.float32).tobytes()
        async with self._iso.session_factory() as s:
            s.add(
                FactorRecord(
                    formula="zeroed", fitness=0.01, formula_embedding=zero
                )
            )
            s.add(
                FactorRecord(
                    formula="real", fitness=0.05, formula_embedding=nonzero
                )
            )
            await s.commit()

        result = await compute_landscape()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["formula"], "real")
