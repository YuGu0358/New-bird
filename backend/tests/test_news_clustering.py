"""Tests for news clustering — pure compute + service with mocked OpenAI/Tavily."""
from __future__ import annotations

import math
import unittest
from typing import Any
from unittest.mock import patch

import pytest

from app.services import news_clustering_service, openai_service, tavily_service
from core.news_clustering import (
    cluster_embeddings,
    cosine_similarity,
    kmeans,
)


# ---------- Pure compute ----------


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_zero():
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite_minus_one():
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector_returns_zero():
    """Avoids div-by-zero — a zero vector has no defined direction."""
    a = [0.0, 0.0]
    b = [1.0, 1.0]
    assert cosine_similarity(a, b) == 0.0


def test_cosine_similarity_length_mismatch_raises():
    with pytest.raises(ValueError, match="same length"):
        cosine_similarity([1.0, 0.0], [1.0])


def test_kmeans_separates_two_clusters():
    """Two clearly-distinct clusters should split into k=2 groups."""
    embeddings = [
        [1.0, 0.0],   # cluster A
        [0.99, 0.01],
        [0.98, 0.02],
        [0.0, 1.0],   # cluster B
        [0.01, 0.99],
        [0.02, 0.98],
    ]
    assignments, centroids = kmeans(embeddings, k=2, seed=42)
    assert len(centroids) == 2
    # First three should share an assignment; last three should share another.
    assert assignments[0] == assignments[1] == assignments[2]
    assert assignments[3] == assignments[4] == assignments[5]
    assert assignments[0] != assignments[3]


def test_kmeans_empty_input_returns_empty():
    assignments, centroids = kmeans([], k=3)
    assert assignments == []
    assert centroids == []


def test_kmeans_clamps_k_above_n():
    """k > N should clamp to N (one cluster per point)."""
    embeddings = [[1.0, 0.0], [0.0, 1.0]]
    _, centroids = kmeans(embeddings, k=10, seed=42)
    assert len(centroids) == 2


def test_kmeans_deterministic_with_seed():
    """Same seed → same assignments."""
    embeddings = [
        [1.0, 0.0], [0.5, 0.5], [0.0, 1.0],
        [-1.0, 0.0], [0.0, -1.0],
    ]
    a1, _ = kmeans(embeddings, k=3, seed=99)
    a2, _ = kmeans(embeddings, k=3, seed=99)
    assert a1 == a2


def test_cluster_embeddings_picks_exemplar():
    """Each non-empty cluster should have an exemplar_index pointing into its members."""
    embeddings = [
        [1.0, 0.0],
        [0.99, 0.01],
        [0.0, 1.0],
        [0.01, 0.99],
    ]
    clusters = cluster_embeddings(embeddings, k=2, seed=42)
    assert len(clusters) == 2
    for c in clusters:
        if c.member_indices:
            assert c.exemplar_index in c.member_indices


def test_cluster_embeddings_empty_input():
    clusters = cluster_embeddings([], k=3)
    assert clusters == []


def test_cluster_embeddings_single_point():
    clusters = cluster_embeddings([[1.0, 0.0]], k=3)
    # k clamped to N=1
    assert len(clusters) == 1
    assert clusters[0].member_indices == [0]
    assert clusters[0].exemplar_index == 0


# ---------- Service (Tavily + OpenAI mocked) ----------


class NewsClusteringServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tavily_service._search_cache.clear()  # noqa: SLF001

    def _stub_headlines(self, count: int = 6) -> dict[str, Any]:
        return {
            "symbol": "AAPL",
            "max_results": count,
            "count": count,
            "headlines": [
                {
                    "title": f"Story {i}",
                    "url": f"https://example.com/{i}",
                    "content": "snippet",
                    "domain": "example.com",
                    "published_date": "2026-04-01",
                    "score": 0.5,
                }
                for i in range(count)
            ],
            "generated_at": "2026-04-01T00:00:00Z",
        }

    def _stub_embeddings(self, count: int) -> Any:
        """Build alternating-direction unit vectors so KMeans has signal."""
        class _Item:
            def __init__(self, vec: list[float]) -> None:
                self.embedding = vec

        class _Resp:
            def __init__(self, items: list[_Item]) -> None:
                self.data = items

        items = []
        for i in range(count):
            angle = (i % 2) * (math.pi / 2)
            items.append(_Item([math.cos(angle), math.sin(angle)]))
        return _Resp(items)

    async def test_raises_when_openai_not_configured(self) -> None:
        with patch.object(openai_service, "is_configured", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                await news_clustering_service.cluster_headlines("AAPL")

    async def test_returns_empty_clusters_when_no_headlines(self) -> None:
        with (
            patch.object(openai_service, "is_configured", return_value=True),
            patch.object(
                tavily_service,
                "fetch_raw_headlines",
                return_value={
                    "symbol": "AAPL",
                    "max_results": 12,
                    "count": 0,
                    "headlines": [],
                    "generated_at": "2026-04-01T00:00:00Z",
                },
            ),
        ):
            payload = await news_clustering_service.cluster_headlines("AAPL")
        self.assertEqual(payload["k_clusters"], 0)
        self.assertEqual(payload["clusters"], [])
        self.assertEqual(payload["headlines"], [])

    async def test_clusters_headlines_into_k_groups(self) -> None:
        headlines = self._stub_headlines(count=6)
        embeddings = self._stub_embeddings(6)

        with (
            patch.object(openai_service, "is_configured", return_value=True),
            patch.object(tavily_service, "fetch_raw_headlines", return_value=headlines),
            patch("app.services.news_clustering_service.openai_service.create_client") as factory,
        ):
            factory.return_value.embeddings.create.return_value = embeddings
            payload = await news_clustering_service.cluster_headlines(
                "AAPL", max_results=6, k_clusters=2
            )

        self.assertEqual(payload["symbol"], "AAPL")
        # 2 alternating directions → exactly 2 non-empty clusters
        self.assertEqual(payload["k_clusters"], 2)
        # Cluster sizes total to 6
        total_members = sum(c["size"] for c in payload["clusters"])
        self.assertEqual(total_members, 6)
        # Densest cluster is first (sort by size desc)
        sizes = [c["size"] for c in payload["clusters"]]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    async def test_falls_back_when_embeddings_empty(self) -> None:
        """If the embeddings call returns nothing, surface headlines as one
        unclustered bucket rather than 502."""

        class _EmptyResp:
            data: list[Any] = []

        with (
            patch.object(openai_service, "is_configured", return_value=True),
            patch.object(
                tavily_service,
                "fetch_raw_headlines",
                return_value=self._stub_headlines(count=3),
            ),
            patch("app.services.news_clustering_service.openai_service.create_client") as factory,
        ):
            factory.return_value.embeddings.create.return_value = _EmptyResp()
            payload = await news_clustering_service.cluster_headlines("AAPL", k_clusters=4)

        self.assertEqual(payload["k_clusters"], 1)
        self.assertEqual(len(payload["clusters"]), 1)
        self.assertEqual(payload["clusters"][0]["size"], 3)


if __name__ == "__main__":
    unittest.main()
