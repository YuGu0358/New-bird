from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock


class _StubAnnotation:
    def __init__(self, kind, label, points):
        self.kind = kind
        self.label = label
        self.points = points


class _StubPoint:
    def __init__(self, timestamp, price):
        self.timestamp = timestamp
        self.price = price


class _StubResponse:
    def __init__(self, annotations):
        self.output_parsed = MagicMock(annotations=annotations)


_TEST_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
)


class ChartAnnotationServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_annotate_returns_normalized_payload(self) -> None:
        from app.services import chart_annotation_service as svc

        bars = [
            {"timestamp": "2026-04-01T00:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 102, "volume": 1000},
            {"timestamp": "2026-04-02T00:00:00+00:00", "open": 102, "high": 108, "low": 101, "close": 107, "volume": 1300},
        ]
        annotations = [
            _StubAnnotation("support", "200 日均线支撑", [_StubPoint("2026-04-01T00:00:00+00:00", 99.0)]),
            _StubAnnotation(
                "trendline",
                "上升趋势线",
                [
                    _StubPoint("2026-04-01T00:00:00+00:00", 100.0),
                    _StubPoint("2026-04-02T00:00:00+00:00", 107.0),
                ],
            ),
        ]
        fake_client = MagicMock()
        fake_client.responses.parse.return_value = _StubResponse(annotations)

        with patch("app.services.chart_annotation_service.create_client", return_value=fake_client):
            result = await svc.annotate_chart("AAPL", "3mo", bars, _TEST_IMAGE_DATA_URL)

        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(len(result["annotations"]), 2)
        first = result["annotations"][0]
        self.assertEqual(first["kind"], "support")
        self.assertEqual(first["label"], "200 日均线支撑")
        self.assertEqual(first["points"][0]["price"], 99.0)
        self.assertIsInstance(first["points"][0]["timestamp"], int)
        self.assertEqual(first["group_id"], "ai-annotation")

    async def test_annotate_with_no_bars_raises_value_error(self) -> None:
        from app.services import chart_annotation_service as svc
        with self.assertRaises(ValueError):
            await svc.annotate_chart("AAPL", "3mo", [], _TEST_IMAGE_DATA_URL)

    async def test_annotate_skips_annotations_with_unparseable_timestamps(self) -> None:
        from app.services import chart_annotation_service as svc

        bars = [
            {"timestamp": "2026-04-01T00:00:00+00:00", "open": 100, "high": 105, "low": 99, "close": 102, "volume": 1000},
        ]
        annotations = [
            _StubAnnotation("support", "好的支撑", [_StubPoint("2026-04-01T00:00:00+00:00", 99.0)]),
            _StubAnnotation("resistance", "坏的时间戳", [_StubPoint("not-a-date", 110.0)]),
        ]
        fake_client = MagicMock()
        fake_client.responses.parse.return_value = _StubResponse(annotations)

        with patch("app.services.chart_annotation_service.create_client", return_value=fake_client):
            result = await svc.annotate_chart("AAPL", "3mo", bars, _TEST_IMAGE_DATA_URL)

        self.assertEqual(len(result["annotations"]), 1)
        self.assertEqual(result["annotations"][0]["kind"], "support")

    async def test_annotate_rejects_missing_image_url(self) -> None:
        from app.services import chart_annotation_service as svc
        bars = [{"timestamp": "2026-04-01T00:00:00+00:00", "open":100,"high":105,"low":99,"close":102,"volume":1000}]
        with self.assertRaises(ValueError):
            await svc.annotate_chart("AAPL", "3mo", bars, "")
        with self.assertRaises(ValueError):
            await svc.annotate_chart("AAPL", "3mo", bars, "not-a-data-url")


class PromptBuildTests(unittest.TestCase):
    def test_prompt_includes_pivots_and_technicals(self) -> None:
        from app.services.chart_annotation_service import _build_prompt

        bars = []
        # Synthesize a W-shape so both swing lows and swing highs exist:
        # 30 down, 30 up (forming first low + middle high), 30 down, 30 up.
        sequence = (
            list(range(30, 0, -1))
            + list(range(0, 30))
            + list(range(30, 0, -1))
            + list(range(0, 30))
        )
        for i, offset in enumerate(sequence):
            close = 50 + offset
            bars.append({
                "timestamp": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
                "open": close, "high": close + 2, "low": close - 2,
                "close": close, "volume": 1_000_000,
            })

        prompt = _build_prompt("AAPL", "6mo", bars)
        # Sanity: contains the technicals header.
        self.assertIn("RSI14", prompt)
        self.assertIn("MA50", prompt)
        self.assertIn("MA200", prompt)
        self.assertIn("swing pivots", prompt)
        # Pivot lines start with "  [low]" or "  [high]".
        self.assertTrue(any(line.lstrip().startswith("[low]") for line in prompt.splitlines()))
        self.assertTrue(any(line.lstrip().startswith("[high]") for line in prompt.splitlines()))


if __name__ == "__main__":
    unittest.main()
