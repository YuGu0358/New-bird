"""Tests for today_recommendations_service."""
from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

import pandas as pd

from tests._factor_test_isolation import (
    factor_test_isolation_setup,
    factor_test_isolation_teardown,
)


class TodayRecommendationsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._iso = await factor_test_isolation_setup(
            services=[
                "today_recommendations_service",
                "multi_factor_score_service",
                "factor_data_service",
                "factor_vector_store",
            ]
        )

    async def asyncTearDown(self) -> None:
        await factor_test_isolation_teardown(self._iso)

    async def test_no_universe_returns_empty(self) -> None:
        from app.services import today_recommendations_service as svc

        with patch.object(
            svc.factor_data_service,
            "get_active_universe",
            new=AsyncMock(return_value=[]),
        ):
            recs = await svc.generate_today_recommendations(date(2026, 5, 1))
        self.assertEqual(recs, [])

    async def test_generates_buy_and_sell_recommendations(self) -> None:
        from app.services import today_recommendations_service as svc

        idx = pd.MultiIndex.from_product(
            [pd.date_range("2026-03-01", periods=30), ["A", "B", "C", "D"]],
            names=["date", "symbol"],
        )
        panel = pd.DataFrame(
            {
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000,
            },
            index=idx,
        ).sort_index()
        score_df = pd.DataFrame(
            {
                "ensemble_rank": [0.9, 0.8, 0.2, 0.1],
                "factor_disagreement": [0.05] * 4,
                "contributing_factors": [
                    [
                        {
                            "factor_id": 1,
                            "formula": "rank(close)",
                            "fitness": 0.05,
                            "rank_value": 0.9,
                            "weight": 1.0,
                        }
                    ]
                ]
                * 4,
            },
            index=["A", "B", "C", "D"],
        )
        with patch.object(
            svc.factor_data_service,
            "get_active_universe",
            new=AsyncMock(return_value=["A", "B", "C", "D"]),
        ), patch.object(
            svc.factor_data_service,
            "get_panel",
            new=AsyncMock(return_value=panel),
        ), patch.object(
            svc.multi_factor_score_service,
            "compute_ensemble_score",
            new=AsyncMock(return_value=score_df),
        ):
            recs = await svc.generate_today_recommendations(
                date(2026, 3, 30), top_k_buy=2, top_k_sell=2
            )

        actions = [r["action"] for r in recs]
        self.assertEqual(sorted(actions), ["buy", "buy", "sell", "sell"])

        for r in recs:
            if r["action"] == "buy":
                self.assertGreater(r["take_profit"], r["entry_high"])
                self.assertLess(r["stop_loss"], r["entry_low"])
            else:
                self.assertLess(r["take_profit"], r["entry_low"])
                self.assertGreater(r["stop_loss"], r["entry_high"])

        # Sum of |position_pct| should respect the gross cap.
        total_gross = sum(abs(r["position_pct"]) for r in recs)
        self.assertLessEqual(total_gross, 80.0 + 1e-6)

    async def test_recommendations_set_position_state_for_held_tickers(self) -> None:
        """Held ticker getting buy → 'add'; new ticker → 'open'."""
        from app.services import today_recommendations_service as svc
        from app.db.tables import PositionOverride

        # Insert a position for AAPL via the isolation session factory.
        async with self._iso.session_factory() as s:
            s.add(
                PositionOverride(
                    broker_account_id=1,
                    ticker="AAPL",
                    stop_price=None,
                    take_profit_price=None,
                    notes="",
                )
            )
            await s.commit()

        idx = pd.MultiIndex.from_product(
            [pd.date_range("2026-04-01", periods=30), ["AAPL", "B", "C", "D"]],
            names=["date", "symbol"],
        )
        panel = pd.DataFrame(
            {
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000,
            },
            index=idx,
        ).sort_index()
        score_df = pd.DataFrame(
            {
                "ensemble_rank": [0.9, 0.8, 0.2, 0.1],
                "factor_disagreement": [0.05] * 4,
                "contributing_factors": [[]] * 4,
            },
            index=["AAPL", "B", "C", "D"],
        )

        with patch.object(
            svc.factor_data_service,
            "get_active_universe",
            new=AsyncMock(return_value=["AAPL", "B", "C", "D"]),
        ), patch.object(
            svc.factor_data_service,
            "get_panel",
            new=AsyncMock(return_value=panel),
        ), patch.object(
            svc.multi_factor_score_service,
            "compute_ensemble_score",
            new=AsyncMock(return_value=score_df),
        ):
            recs = await svc.generate_today_recommendations(
                date(2026, 4, 30), top_k_buy=2, top_k_sell=2
            )

        aapl = next(r for r in recs if r["symbol"] == "AAPL")
        # Held ticker getting a buy signal → 'add'.
        self.assertEqual(aapl["position_state"], "add")
        # The underlying action stays 'buy' so frontend filters still work.
        self.assertEqual(aapl["action"], "buy")
        # A non-held ticker stays 'open'.
        non_held = next(r for r in recs if r["symbol"] != "AAPL")
        self.assertEqual(non_held["position_state"], "open")


if __name__ == "__main__":
    unittest.main()
