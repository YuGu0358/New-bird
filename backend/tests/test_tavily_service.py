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

    async def test_fetch_raw_headlines_returns_individual_articles(self) -> None:
        """Raw headlines path should NOT call the LLM and should return per-article rows."""
        mock_response = {
            "results": [
                {
                    "title": "AAPL beats Q1 estimates",
                    "url": "https://example.com/a",
                    "content": "Apple beat earnings on services growth.",
                    "domain": "example.com",
                    "published_date": "2026-04-15",
                    "score": 0.95,
                },
                {
                    "title": "iPhone supply update",
                    "url": "https://example.com/b",
                    "content": "Production targets unchanged for Q3.",
                    "domain": "example.com",
                    "published_date": "2026-04-14",
                    "score": 0.80,
                },
            ],
        }
        with patch("app.services.tavily_service._create_client") as client_factory:
            client_factory.return_value.search.return_value = mock_response
            payload = await tavily_service.fetch_raw_headlines("aapl", max_results=5)

            # Verify Tavily was called with include_answer=False (no LLM round-trip)
            search_kwargs = client_factory.return_value.search.call_args.kwargs
            self.assertFalse(search_kwargs["include_answer"])
            self.assertEqual(search_kwargs["max_results"], 5)

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["max_results"], 5)
        self.assertEqual(len(payload["headlines"]), 2)
        self.assertEqual(payload["headlines"][0]["title"], "AAPL beats Q1 estimates")
        self.assertEqual(payload["headlines"][0]["domain"], "example.com")

    async def test_fetch_raw_headlines_clamps_max_results(self) -> None:
        """max_results should be clamped to [1, 20]."""
        with patch("app.services.tavily_service._create_client") as client_factory:
            client_factory.return_value.search.return_value = {"results": []}
            await tavily_service.fetch_raw_headlines("AAPL", max_results=999)
            self.assertEqual(
                client_factory.return_value.search.call_args.kwargs["max_results"], 20
            )

            tavily_service._search_cache.clear()  # noqa: SLF001
            await tavily_service.fetch_raw_headlines("AAPL", max_results=0)
            self.assertEqual(
                client_factory.return_value.search.call_args.kwargs["max_results"], 1
            )

    async def test_fetch_raw_headlines_caches_per_symbol_and_count(self) -> None:
        """Two calls within TTL with the same (symbol, max_results) → 1 fetch."""
        with patch("app.services.tavily_service._create_client") as client_factory:
            client_factory.return_value.search.return_value = {"results": []}
            await tavily_service.fetch_raw_headlines("NVDA", max_results=5)
            await tavily_service.fetch_raw_headlines("NVDA", max_results=5)
            self.assertEqual(client_factory.return_value.search.call_count, 1)

    async def test_fetch_raw_headlines_skips_results_without_url(self) -> None:
        """Tavily rows missing URL should be dropped (mirrors search_web behavior)."""
        mock_response = {
            "results": [
                {"title": "no url", "content": "x"},
                {"title": "ok", "url": "https://example.com/x", "content": "y"},
            ],
        }
        with patch("app.services.tavily_service._create_client") as client_factory:
            client_factory.return_value.search.return_value = mock_response
            payload = await tavily_service.fetch_raw_headlines("AAPL", max_results=10)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["headlines"][0]["title"], "ok")
