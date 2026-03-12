from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services import monitoring_service


class MonitoringServiceTests(unittest.TestCase):
    def test_select_reference_price_uses_prior_window(self) -> None:
        now = datetime(2026, 3, 12, tzinfo=timezone.utc)
        points = [
            (now - timedelta(days=10), 95.0),
            (now - timedelta(days=7), 100.0),
            (now - timedelta(days=5), 103.0),
            (now, 110.0),
        ]

        price = monitoring_service._select_reference_price(  # noqa: SLF001
            points,
            lookback_days=7,
            fallback_index=5,
        )

        self.assertEqual(price, 100.0)

    def test_build_trend_snapshot_prefers_live_price_for_day_change(self) -> None:
        now = datetime(2026, 3, 12, tzinfo=timezone.utc)
        history = [
            (now - timedelta(days=31), 90.0),
            (now - timedelta(days=7), 100.0),
            (now - timedelta(days=1), 104.0),
            (now, 106.0),
        ]

        snapshot = monitoring_service._build_trend_snapshot(  # noqa: SLF001
            "NVDA",
            history,
            {"price": 108.0, "previous_close": 104.0},
            now,
        )

        self.assertAlmostEqual(snapshot["day_change_percent"], 3.8461, places=3)
        self.assertAlmostEqual(snapshot["week_change_percent"], 8.0, places=3)
        self.assertAlmostEqual(snapshot["month_change_percent"], 20.0, places=3)
        self.assertEqual(snapshot["month_direction"], "up")

    def test_score_candidate_weights_short_and_medium_term_momentum(self) -> None:
        score = monitoring_service._score_candidate(  # noqa: SLF001
            {
                "day_change_percent": 2.0,
                "week_change_percent": 6.0,
                "month_change_percent": 10.0,
            }
        )

        self.assertAlmostEqual(score, 7.0, places=4)


if __name__ == "__main__":
    unittest.main()
