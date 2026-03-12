from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.services import social_intelligence_service
from app.services.social_providers.x_provider import build_x_query


class SocialIntelligenceServiceTests(unittest.TestCase):
    def test_build_x_query_appends_common_filters(self) -> None:
        query = build_x_query(
            "NVDA AI",
            lang="en",
            exclude_reposts=True,
            exclude_replies=True,
        )

        self.assertIn("NVDA AI", query)
        self.assertIn("lang:en", query)
        self.assertIn("-is:retweet", query)
        self.assertIn("-is:reply", query)

    def test_filter_and_rank_posts_applies_thresholds_and_exclude_terms(self) -> None:
        now = datetime(2026, 3, 12, tzinfo=timezone.utc)
        posts = [
            {
                "provider": "x",
                "post_id": "1",
                "text": "NVDA AI demand keeps climbing.",
                "created_at": now.isoformat(),
                "url": "https://x.com/test/status/1",
                "author": {"id": "u1", "username": "alpha", "verified": True, "followers_count": 150000},
                "metrics": {"like_count": 400, "repost_count": 120, "reply_count": 30, "quote_count": 10},
            },
            {
                "provider": "x",
                "post_id": "2",
                "text": "spam alert for NVDA",
                "created_at": (now - timedelta(hours=1)).isoformat(),
                "url": "https://x.com/test/status/2",
                "author": {"id": "u2", "username": "beta", "verified": False, "followers_count": 100},
                "metrics": {"like_count": 500, "repost_count": 40, "reply_count": 10, "quote_count": 0},
            },
            {
                "provider": "x",
                "post_id": "3",
                "text": "NVDA mention with too little traction",
                "created_at": (now - timedelta(hours=2)).isoformat(),
                "url": "https://x.com/test/status/3",
                "author": {"id": "u3", "username": "gamma", "verified": False, "followers_count": 50},
                "metrics": {"like_count": 2, "repost_count": 0, "reply_count": 0, "quote_count": 0},
            },
        ]

        ranked = social_intelligence_service._filter_and_rank_posts(  # noqa: SLF001
            posts,
            query="NVDA AI",
            limit=5,
            min_like_count=10,
            min_repost_count=5,
            exclude_terms=("spam",),
        )

        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["post_id"], "1")
        self.assertIn("nvda", ranked[0]["matched_terms"])
        self.assertGreater(ranked[0]["score"], 0.0)

    def test_fallback_summary_mentions_total_counts(self) -> None:
        posts = [
            {
                "author": {"username": "alpha"},
                "metrics": {"like_count": 200, "repost_count": 50},
                "matched_terms": ["nvda", "ai"],
            }
        ]
        counts = [{"start": "", "end": "", "post_count": 128}]

        summary = social_intelligence_service._fallback_social_summary(  # noqa: SLF001
            "NVDA AI",
            posts,
            counts,
        )

        self.assertIn("NVDA AI", summary)
        self.assertIn("128", summary)
        self.assertIn("@alpha", summary)


if __name__ == "__main__":
    unittest.main()
