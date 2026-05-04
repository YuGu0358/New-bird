from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete

from app.database import AsyncSessionLocal, SocialSignalSnapshot, init_database
from app.services import social_signal_service


def _sample_post(symbol: str, text: str, *, hours_ago: int = 1, likes: int = 50) -> dict[str, object]:
    created_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "provider": "x",
        "post_id": f"{symbol}-{hours_ago}-{likes}",
        "text": text,
        "created_at": created_at,
        "url": f"https://x.com/test/status/{symbol}-{hours_ago}-{likes}",
        "lang": "en",
        "author": {
            "id": "u1",
            "username": "alpha",
            "display_name": "Alpha",
            "verified": True,
            "followers_count": 120000,
        },
        "metrics": {
            "like_count": likes,
            "repost_count": max(1, likes // 5),
            "reply_count": max(1, likes // 10),
            "quote_count": max(0, likes // 20),
        },
        "score": 5.0,
        "matched_terms": [symbol.lower()],
    }


class SocialSignalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await init_database()
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SocialSignalSnapshot))
            await session.commit()

    async def asyncTearDown(self) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(delete(SocialSignalSnapshot))
            await session.commit()

    async def test_build_query_profile_includes_symbol_company_and_context(self) -> None:
        with patch(
            "app.services.company_profile_service.get_company_profile",
            new=AsyncMock(return_value={"company_name": "NVIDIA Corporation"}),
        ):
            payload = await social_signal_service.build_query_profile(
                "NVDA",
                keywords=("AI infra", "datacenter"),
                hours=8,
                lang="en",
            )

        self.assertEqual(payload["symbol"], "NVDA")
        self.assertEqual(payload["company_name"], "NVIDIA Corporation")
        self.assertIn("NVDA", payload["x_query"])
        self.assertIn("NVIDIA Corporation", payload["x_query"])
        self.assertIn("earnings", payload["x_query"])
        self.assertIn("latest market sentiment catalysts", payload["tavily_query"])
        self.assertEqual(payload["hours"], 8)

    def test_local_classifier_marks_direction_and_irrelevant_text(self) -> None:
        bullish = social_signal_service._local_classify_text(  # noqa: SLF001
            "NVDA beats earnings and raised guidance with strong demand.",
            symbol="NVDA",
            aliases=["NVIDIA", "nvidia"],
        )
        bearish = social_signal_service._local_classify_text(  # noqa: SLF001
            "NVDA faces a downgrade after weak guidance and margin pressure.",
            symbol="NVDA",
            aliases=["NVIDIA", "nvidia"],
        )
        irrelevant = social_signal_service._local_classify_text(  # noqa: SLF001
            "TSLA demand looks strong this quarter.",
            symbol="NVDA",
            aliases=["NVIDIA", "nvidia"],
        )

        self.assertEqual(bullish.label, "bullish")
        self.assertEqual(bearish.label, "bearish")
        self.assertEqual(irrelevant.label, "irrelevant")
        self.assertFalse(irrelevant.mention_entity)

    def test_social_score_penalizes_controversy(self) -> None:
        posts = [
            {
                "classification": {"label": "bullish", "confidence": 0.9},
                "weight": 2.0,
            },
            {
                "classification": {"label": "bearish", "confidence": 0.9},
                "weight": 2.0,
            },
            {
                "classification": {"label": "bullish", "confidence": 0.9},
                "weight": 1.0,
            },
        ]

        score, controversy_penalty, relevant_count = social_signal_service._aggregate_social_score(posts)  # noqa: SLF001

        self.assertEqual(relevant_count, 3)
        self.assertGreater(score, 0.0)
        self.assertGreater(controversy_penalty, 0.0)

    def test_market_score_and_action_mapping_respect_no_short_rule(self) -> None:
        trend = {
            "day_change_percent": 4.0,
            "week_change_percent": 12.0,
            "month_change_percent": 28.0,
        }
        market_score = social_signal_service._compute_market_score(trend)  # noqa: SLF001
        avoid_action = social_signal_service._map_action(-35.0, has_position=False)  # noqa: SLF001
        sell_action = social_signal_service._map_action(-55.0, has_position=True)  # noqa: SLF001

        self.assertGreater(market_score, 0.0)
        self.assertEqual(avoid_action, "avoid")
        self.assertEqual(sell_action, "sell")

    async def test_score_symbol_signal_builds_sell_signal_and_persists_snapshot(self) -> None:
        posts = [
            _sample_post("NVDA", "NVDA weak guidance and downgrade pressure keep getting worse.", likes=80),
            _sample_post("NVDA", "NVDA faces another downgrade after a weak quarter.", likes=65),
            _sample_post("NVDA", "Bearish on NVDA after weak demand and margin pressure.", likes=72),
            _sample_post("NVDA", "NVDA looks overvalued and the downgrade cycle continues.", likes=55),
            _sample_post("NVDA", "Sell NVDA into the bounce, weak guidance is a real problem.", likes=60),
        ]
        sources = {
            "query": "NVDA",
            "topic": "news",
            "answer": "Negative coverage.",
            "generated_at": datetime.now(timezone.utc),
            "results": [
                {
                    "title": "Analyst cuts NVDA rating",
                    "url": "https://example.com/1",
                    "content": "Downgrade and weak demand outlook.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.91,
                },
                {
                    "title": "Guidance cut raises concern",
                    "url": "https://example.com/2",
                    "content": "Weak outlook and valuation pressure.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.84,
                },
                {
                    "title": "Margin pressure persists",
                    "url": "https://example.com/3",
                    "content": "Bearish revision on earnings expectations.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.79,
                },
            ],
        }

        with (
            patch(
                "app.services.social_signal.runner.build_query_profile",
                new=AsyncMock(
                    return_value={
                        "symbol": "NVDA",
                        "company_name": "NVIDIA Corporation",
                        "keywords": [],
                        "context_terms": ["earnings", "guidance"],
                        "x_query": "NVDA",
                        "tavily_query": "NVDA NVIDIA latest market sentiment catalysts",
                        "lang": "en",
                        "hours": 6,
                    }
                ),
            ),
            patch(
                "app.services.social_intelligence_service.search_social_posts",
                new=AsyncMock(return_value={"posts": posts, "counts": [], "normalized_query": "NVDA"}),
            ),
            patch(
                "app.services.tavily_service.search_web",
                new=AsyncMock(return_value=sources),
            ),
            patch(
                "app.services.monitoring_service.fetch_trend_snapshots",
                new=AsyncMock(
                    return_value={
                        "NVDA": {
                            "symbol": "NVDA",
                            "as_of": datetime.now(timezone.utc),
                            "day_change_percent": -6.0,
                            "week_change_percent": -15.0,
                            "month_change_percent": -32.0,
                        }
                    }
                ),
            ),
            patch(
                "app.services.social_signal.runner._load_positions_map",
                new=AsyncMock(return_value={"NVDA": {"symbol": "NVDA", "qty": 5}}),
            ),
        ):
            async with AsyncSessionLocal() as session:
                payload = await social_signal_service.score_symbol_signal(session, symbol="NVDA")

        self.assertIn(payload["action"], {"sell", "reduce_or_sell"})
        self.assertLess(payload["final_weight"], -25.0)
        self.assertEqual(payload["executed"], False)

        async with AsyncSessionLocal() as session:
            latest = await social_signal_service.get_latest_signals(session, symbol="NVDA", limit=5)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["symbol"], "NVDA")
        self.assertTrue(latest[0]["reasons"])

    async def test_score_symbol_signal_blocks_execution_when_auto_trade_disabled(self) -> None:
        posts = [
            _sample_post("AAPL", "AAPL beats earnings with strong demand and upgrade momentum.", likes=90),
            _sample_post("AAPL", "Bullish on AAPL after strong product demand.", likes=70),
            _sample_post("AAPL", "AAPL guidance raised and margins improved.", likes=66),
            _sample_post("AAPL", "Buy AAPL as revenue growth remains strong.", likes=58),
            _sample_post("AAPL", "AAPL rally supported by strong upgrade cycle.", likes=52),
        ]
        sources = {
            "query": "AAPL",
            "topic": "news",
            "answer": "Positive coverage.",
            "generated_at": datetime.now(timezone.utc),
            "results": [
                {
                    "title": "AAPL earnings beat",
                    "url": "https://example.com/a",
                    "content": "Strong demand and raised guidance.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.92,
                },
                {
                    "title": "Analysts upgrade AAPL",
                    "url": "https://example.com/b",
                    "content": "Bullish revisions after strong quarter.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.86,
                },
                {
                    "title": "Demand remains strong",
                    "url": "https://example.com/c",
                    "content": "Positive product cycle outlook.",
                    "source": "Example",
                    "domain": "example.com",
                    "published_date": "2026-04-04",
                    "score": 0.8,
                },
            ],
        }

        with (
            patch(
                "app.services.social_signal.runner.build_query_profile",
                new=AsyncMock(
                    return_value={
                        "symbol": "AAPL",
                        "company_name": "Apple Inc.",
                        "keywords": [],
                        "context_terms": ["earnings", "guidance"],
                        "x_query": "AAPL",
                        "tavily_query": "AAPL Apple latest market sentiment catalysts",
                        "lang": "en",
                        "hours": 6,
                    }
                ),
            ),
            patch(
                "app.services.social_intelligence_service.search_social_posts",
                new=AsyncMock(return_value={"posts": posts, "counts": [], "normalized_query": "AAPL"}),
            ),
            patch(
                "app.services.tavily_service.search_web",
                new=AsyncMock(return_value=sources),
            ),
            patch(
                "app.services.monitoring_service.fetch_trend_snapshots",
                new=AsyncMock(
                    return_value={
                        "AAPL": {
                            "symbol": "AAPL",
                            "as_of": datetime.now(timezone.utc),
                            "day_change_percent": 5.0,
                            "week_change_percent": 12.0,
                            "month_change_percent": 24.0,
                        }
                    }
                ),
            ),
            patch(
                "app.services.social_signal.runner._load_positions_map",
                new=AsyncMock(return_value={}),
            ),
        ):
            async with AsyncSessionLocal() as session:
                payload = await social_signal_service.score_symbol_signal(
                    session,
                    symbol="AAPL",
                    execute=True,
                )

        self.assertEqual(payload["action"], "buy")
        self.assertFalse(payload["executed"])
        self.assertIn("未开启社媒自动交易", payload["execution_message"])

    async def test_score_symbol_signal_degrades_when_social_sources_fail(self) -> None:
        with (
            patch(
                "app.services.social_signal.runner.build_query_profile",
                new=AsyncMock(
                    return_value={
                        "symbol": "AAPL",
                        "company_name": "Apple Inc.",
                        "keywords": [],
                        "context_terms": ["earnings", "guidance"],
                        "x_query": "AAPL",
                        "tavily_query": "AAPL Apple latest market sentiment catalysts",
                        "lang": "en",
                        "hours": 6,
                    }
                ),
            ),
            patch(
                "app.services.social_intelligence_service.search_social_posts",
                new=AsyncMock(side_effect=RuntimeError("X token missing")),
            ),
            patch(
                "app.services.tavily_service.search_web",
                new=AsyncMock(side_effect=RuntimeError("Tavily API key is missing")),
            ),
            patch(
                "app.services.monitoring_service.fetch_trend_snapshots",
                new=AsyncMock(
                    return_value={
                        "AAPL": {
                            "symbol": "AAPL",
                            "as_of": datetime.now(timezone.utc),
                            "day_change_percent": 0.2,
                            "week_change_percent": 0.5,
                            "month_change_percent": 1.0,
                        }
                    }
                ),
            ),
            patch(
                "app.services.social_signal.runner._load_positions_map",
                new=AsyncMock(return_value={}),
            ),
        ):
            async with AsyncSessionLocal() as session:
                payload = await social_signal_service.score_symbol_signal(session, symbol="AAPL")

        self.assertEqual(payload["symbol"], "AAPL")
        self.assertEqual(payload["confidence_label"], "low")
        self.assertIn(payload["action"], {"hold", "bullish_watch", "avoid"})
        self.assertEqual(payload["top_posts"], [])
        self.assertEqual(payload["top_sources"], [])
        self.assertTrue(any("X" in reason for reason in payload["reasons"]))
        self.assertTrue(any("Tavily" in reason for reason in payload["reasons"]))


if __name__ == "__main__":
    unittest.main()
