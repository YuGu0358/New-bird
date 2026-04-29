"""News clustering — pure compute helpers (KMeans + cosine)."""
from core.news_clustering.compute import (
    NewsCluster,
    cluster_embeddings,
    cosine_similarity,
    kmeans,
)

__all__ = [
    "NewsCluster",
    "cluster_embeddings",
    "cosine_similarity",
    "kmeans",
]
