from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import tavily_service


class TavilyServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tavily_service._search_cache.clear()  # noqa: SLF001

    async def test_search_web_returns_answer_and_sources(self) -> None:
        mock_response = {
            "answer": "AAPL 近期焦点集中在新品预期和服务业务增长。",
            "results": [
                {
                    "title": "Apple services keep growing",
                    "url": "https://example.com/apple-services",
                    "content": "Services revenue remained resilient and margins improved.",
                    "source": "Example News",
                    "domain": "example.com",
                    "published_date": "2026-03-24",
                    "score": 0.91,
                }
            ],
        }

        with patch(
            "app.services.tavily_service._create_client",
        ) as client_factory:
            client_factory.return_value.search.return_value = mock_response
            payload = await tavily_service.search_web("AAPL latest outlook", topic="news")

        self.assertEqual(payload["query"], "AAPL latest outlook")
        self.assertEqual(payload["topic"], "news")
        self.assertIn("AAPL", payload["answer"])
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["title"], "Apple services keep growing")
        self.assertEqual(payload["results"][0]["domain"], "example.com")

    async def test_search_web_rejects_empty_query(self) -> None:
        with self.assertRaisesRegex(ValueError, "搜索关键词不能为空"):
            await tavily_service.search_web("", topic="general")
