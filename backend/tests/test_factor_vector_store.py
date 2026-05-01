from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import numpy as np
from sqlalchemy import delete

from app.database import init_database
from app.db.engine import AsyncSessionLocal
from app.db.tables import FactorRecord


class FactorVectorStoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await init_database()
        # Wipe state between tests so dedupe / formula uniqueness assertions
        # don't depend on rows left behind by prior test runs.
        async with AsyncSessionLocal() as session:
            await session.execute(delete(FactorRecord))
            await session.commit()

    async def test_add_and_list_factor(self) -> None:
        from app.services import factor_vector_store as svc

        embed = np.random.RandomState(0).randn(1536).astype(np.float32)
        with patch.object(svc, "embed_formula", new=AsyncMock(return_value=embed)):
            row_id = await svc.add_factor("rank(close)", fitness=0.05, ic_5d=0.04)
        self.assertIsNotNone(row_id)
        rows = await svc.list_factors()
        self.assertGreaterEqual(len(rows), 1)

    async def test_dedupe_rejects_identical_formula(self) -> None:
        from app.services import factor_vector_store as svc

        embed = np.random.RandomState(1).randn(1536).astype(np.float32)
        with patch.object(svc, "embed_formula", new=AsyncMock(return_value=embed)):
            await svc.add_factor("rank(volume)", fitness=0.03)
            second = await svc.add_factor("rank(volume)", fitness=0.04)
        self.assertIsNone(second)

    async def test_embed_return_series_shape(self) -> None:
        from app.services import factor_vector_store as svc

        v = svc.embed_return_series(np.random.randn(500).astype(np.float32))
        self.assertEqual(v.shape, (256,))

    async def test_embed_return_series_pads_short_input(self) -> None:
        from app.services import factor_vector_store as svc

        v = svc.embed_return_series(np.array([0.01, 0.02]))
        self.assertEqual(v.shape, (256,))
        self.assertEqual(float(v[-1]), 0.0)


if __name__ == "__main__":
    unittest.main()
