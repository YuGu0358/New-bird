from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services import chart_service


class _FakeFrame:
    def __init__(self, rows):
        self._rows = rows
        self.empty = len(rows) == 0

    def iterrows(self):
        for item in self._rows:
            yield item


class ChartServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        chart_service._chart_cache.clear()  # noqa: SLF001

    def test_frame_to_points_filters_zero_close(self) -> None:
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        frame = _FakeFrame(
            [
                (
                    now - timedelta(days=1),
                    {"Open": 100, "High": 105, "Low": 98, "Close": 102, "Volume": 1200},
                ),
                (
                    now,
                    {"Open": 102, "High": 103, "Low": 99, "Close": 0, "Volume": 800},
                ),
            ]
        )

        points = chart_service._frame_to_points(frame)  # noqa: SLF001

        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["close"], 102.0)
        self.assertEqual(points[0]["volume"], 1200)

    async def test_get_symbol_chart_returns_latest_price_and_change(self) -> None:
        now = datetime(2026, 3, 15, tzinfo=timezone.utc)
        frame = _FakeFrame(
            [
                (
                    now - timedelta(days=3),
                    {"Open": 98, "High": 100, "Low": 97, "Close": 100, "Volume": 900},
                ),
                (
                    now - timedelta(days=2),
                    {"Open": 100, "High": 103, "Low": 99, "Close": 102, "Volume": 1100},
                ),
                (
                    now - timedelta(days=1),
                    {"Open": 102, "High": 106, "Low": 101, "Close": 105, "Volume": 1500},
                ),
            ]
        )

        with patch(
            "app.services.chart_service._download_chart_frame_sync",
            return_value=frame,
        ) as download_mock:
            payload = await chart_service.get_symbol_chart("nvda", "1mo")

        # 1mo now uses 1h bars (was 1d) to surface intraday detail.
        download_mock.assert_called_once_with("NVDA", "1mo", "1h")
        self.assertEqual(payload["symbol"], "NVDA")
        self.assertEqual(payload["range"], "1mo")
        self.assertEqual(payload["interval"], "1h")
        self.assertEqual(payload["latest_price"], 105.0)
        self.assertEqual(payload["range_change_percent"], 5.0)
        self.assertEqual(len(payload["points"]), 3)

    async def test_get_symbol_chart_rejects_unsupported_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "不支持的走势图区间"):
            await chart_service.get_symbol_chart("NVDA", "10y")

    async def test_get_symbol_chart_supports_intraday_range(self) -> None:
        now = datetime(2026, 3, 15, 14, 0, tzinfo=timezone.utc)
        frame = _FakeFrame(
            [
                (
                    now - timedelta(minutes=10),
                    {"Open": 100, "High": 101, "Low": 99.8, "Close": 100.5, "Volume": 800},
                ),
                (
                    now - timedelta(minutes=5),
                    {"Open": 100.5, "High": 101.4, "Low": 100.1, "Close": 101.2, "Volume": 920},
                ),
            ]
        )

        with patch(
            "app.services.chart_service._download_chart_frame_sync",
            return_value=frame,
        ) as download_mock:
            payload = await chart_service.get_symbol_chart("aapl", "1d")

        # 1d now uses 1m bars (was 5m) so per-minute moves are visible.
        download_mock.assert_called_once_with("AAPL", "1d", "1m")
        self.assertEqual(payload["range"], "1d")
        self.assertEqual(payload["interval"], "1m")
        self.assertEqual(payload["latest_price"], 101.2)


if __name__ == "__main__":
    unittest.main()
