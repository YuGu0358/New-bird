"""Tests for the multi-factor ensemble scoring service."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd


class MultiFactorScoreServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_library_returns_empty_df(self) -> None:
        from app.services import multi_factor_score_service as svc

        with patch.object(
            svc.factor_vector_store,
            "list_factors",
            new=AsyncMock(return_value=[]),
        ):
            df = await svc.compute_ensemble_score(["AAPL"], date(2026, 5, 1))
        self.assertTrue(df.empty)

    async def test_ranks_aggregated_across_factors(self) -> None:
        from app.services import multi_factor_score_service as svc

        # Synthesize 3-symbol panel where close per-symbol is monotonic and
        # symbol C has the highest close; rank(close) is the formula so C
        # should win the ensemble rank on the latest date.
        idx = pd.MultiIndex.from_product(
            [pd.date_range("2026-01-01", periods=80), ["A", "B", "C"]],
            names=["date", "symbol"],
        )
        panel = pd.DataFrame(
            {
                "open": np.tile([10, 20, 30], 80) + np.repeat(np.arange(80) * 0.1, 3),
                "high": np.tile([10, 20, 30], 80) + 1 + np.repeat(np.arange(80) * 0.1, 3),
                "low": np.tile([10, 20, 30], 80) - 1 + np.repeat(np.arange(80) * 0.1, 3),
                "close": np.tile([10, 20, 30], 80) + np.repeat(np.arange(80) * 0.1, 3),
                "volume": 1_000_000,
            },
            index=idx,
        ).sort_index()

        with patch.object(
            svc.factor_vector_store,
            "list_factors",
            new=AsyncMock(
                return_value=[
                    {
                        "id": 1,
                        "formula": "rank(close)",
                        "fitness": 0.05,
                        "ic_5d": 0.04,
                    }
                ]
            ),
        ), patch.object(
            svc.factor_data_service,
            "get_panel",
            new=AsyncMock(return_value=panel),
        ):
            df = await svc.compute_ensemble_score(
                ["A", "B", "C"], date(2026, 3, 21)
            )

        self.assertFalse(df.empty)
        self.assertEqual(df["ensemble_rank"].idxmax(), "C")
        self.assertIn("contributing_factors", df.columns)
        self.assertIn("factor_disagreement", df.columns)


if __name__ == "__main__":
    unittest.main()
