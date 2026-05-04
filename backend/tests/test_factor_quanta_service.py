from __future__ import annotations

import random
import unittest
from unittest.mock import AsyncMock, patch

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class _StubLLMResp:
    def __init__(self, direction: str, intuition: str, formula: str) -> None:
        self.research_direction = direction
        self.math_intuition = intuition
        self.formula = formula


class FactorQuantaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._iso = await factor_test_isolation_setup(
            services=["factor_quanta_service"]
        )

    async def asyncTearDown(self):
        await factor_test_isolation_teardown(self._iso)

    async def test_generate_trajectory_persists_valid_formula(self):
        from app.services import factor_quanta_service as svc

        with patch.object(
            svc,
            "_safe_llm_call",
            new=AsyncMock(
                return_value=_StubLLMResp(
                    "momentum reversal at 20d ma",
                    "rolling mean over 20 days then rank cross-section",
                    "rank(ts_mean(close,20))",
                )
            ),
        ):
            draft = await svc.generate_trajectory(recent_pool=[])
        self.assertIsNotNone(draft)
        self.assertEqual(draft.formula, "rank(ts_mean(close,20))")
        row_id = await svc.persist_trajectory(draft)
        self.assertIsNotNone(row_id)
        rows = await svc.list_trajectories()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["evolution_step"], "seed")

    async def test_generate_drops_unparseable_formula(self):
        from app.services import factor_quanta_service as svc

        with patch.object(
            svc,
            "_safe_llm_call",
            new=AsyncMock(
                return_value=_StubLLMResp(
                    "garbage",
                    "junk",
                    "not-a-real-formula!!",
                )
            ),
        ):
            draft = await svc.generate_trajectory(recent_pool=[])
        self.assertIsNone(draft)

    async def test_evolve_carries_parent_id_and_failure_reason(self):
        from app.services import factor_quanta_service as svc

        parent = {
            "id": 7,
            "research_direction": "x",
            "math_intuition": "y",
            "formula": "rank(close)",
        }
        with patch.object(
            svc,
            "_safe_llm_call",
            new=AsyncMock(
                return_value=_StubLLMResp(
                    "x revised",
                    "y revised",
                    "rank(ts_mean(close,5))",
                )
            ),
        ):
            draft = await svc.evolve_trajectory(
                parent, failure_reason="ic too low", recent_pool=[]
            )
        self.assertEqual(draft.parent_id, 7)
        self.assertEqual(draft.evolution_step, "evolve")
        self.assertEqual(draft.failure_reason, "ic too low")

    async def test_pick_parents_uses_top_half(self):
        from app.services import factor_quanta_service as svc

        rng = random.Random(0)
        library = [{"id": i, "fitness": float(i)} for i in range(10)]
        chosen = svc.pick_parents_for_quanta(library, 5, rng)
        self.assertEqual(len(chosen), 5)
        # Top half = ids 5..9 (sorted desc by fitness, take first 5)
        for p in chosen:
            self.assertGreaterEqual(p["id"], 5)


if __name__ == "__main__":
    unittest.main()
