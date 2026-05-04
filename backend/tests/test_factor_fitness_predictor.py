"""Tests for the Factor Forge fitness predictor."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from core.factors.ast import parse

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class FitnessPredictorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        # Service uses factor_vector_store.list_factors so patch both modules.
        self._iso = await factor_test_isolation_setup(
            services=["factor_fitness_predictor", "factor_vector_store"]
        )

    async def asyncTearDown(self) -> None:
        await factor_test_isolation_teardown(self._iso)

    async def test_features_have_fixed_dim(self) -> None:
        from app.services.factor_fitness_predictor import (
            FEATURE_DIM,
            features_from_node,
        )

        node = parse("rank(close)")
        v = features_from_node(node)
        self.assertEqual(v.shape, (FEATURE_DIM,))

    async def test_features_count_ops_and_cols(self) -> None:
        from app.services.factor_fitness_predictor import (
            _COL_VOCAB,
            _OPS_VOCAB,
            features_from_node,
        )

        node = parse("add(rank(close), rank(volume))")
        v = features_from_node(node)

        rank_idx = 2 + _OPS_VOCAB.index("rank")
        self.assertEqual(int(v[rank_idx]), 2)

        close_idx = 2 + len(_OPS_VOCAB) + _COL_VOCAB.index("close")
        volume_idx = 2 + len(_OPS_VOCAB) + _COL_VOCAB.index("volume")
        self.assertEqual(int(v[close_idx]), 1)
        self.assertEqual(int(v[volume_idx]), 1)

    async def test_untrained_predict_returns_zero(self) -> None:
        from app.services.factor_fitness_predictor import FitnessPredictor

        p = FitnessPredictor()
        self.assertFalse(p.is_trained)
        self.assertEqual(p.predict(parse("rank(close)")), 0.0)

    async def test_train_skips_when_insufficient_data(self) -> None:
        from app.services import factor_fitness_predictor as svc

        with patch.object(
            svc.factor_vector_store,
            "list_factors",
            new=AsyncMock(return_value=[]),
        ):
            predictor = await svc.train_from_library(min_records=10)
        self.assertFalse(predictor.is_trained)

    async def test_train_with_synthetic_records_produces_useful_predictor(
        self,
    ) -> None:
        """Synthetic IC pattern: rank(close) -> +0.05, add(close,volume) -> -0.01.

        Trained predictor should rank the rank-using formula above the
        non-rank one.
        """
        from app.services import factor_fitness_predictor as svc

        synthetic = []
        for i in range(50):
            uses_rank = i % 2 == 0
            formula = "rank(close)" if uses_rank else "add(close,volume)"
            ic = 0.05 if uses_rank else -0.01
            synthetic.append(
                {
                    "formula": formula,
                    "ic_5d": ic,
                    "fitness": ic,
                }
            )

        with patch.object(
            svc.factor_vector_store,
            "list_factors",
            new=AsyncMock(return_value=synthetic),
        ), patch.object(svc, "_persist_model", lambda _m: None):
            predictor = await svc.train_from_library(min_records=10)

        self.assertTrue(predictor.is_trained)
        rank_pred = predictor.predict(parse("rank(close)"))
        no_rank_pred = predictor.predict(parse("add(close,volume)"))
        self.assertGreater(rank_pred, no_rank_pred)


if __name__ == "__main__":
    unittest.main()
