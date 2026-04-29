"""Pure-compute clustering for news embeddings.

Why pure Python: with N=10–20 headlines and 1536-dim embeddings, a from-
scratch Lloyd's KMeans converges in milliseconds and adds zero deps. scikit-
learn would be heavier than the rest of the request.

Inputs are raw float vectors (already normalized by the embedding API). The
algorithm:
1. Seed centroids by k-means++ (variance-aware random init for stability).
2. Assign each point to its nearest centroid by *cosine distance* (1 − cosine
   similarity). For text embeddings cosine is the standard distance metric;
   Euclidean would over-weight magnitude differences that text-embeddings
   are insensitive to.
3. Update centroids to the mean of their members; re-normalize so cosine
   stays well-defined.
4. Stop when membership stops changing or after `max_iter`.

Pure compute, no I/O, deterministic when `seed` is provided.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class NewsCluster:
    cluster_id: int
    member_indices: list[int] = field(default_factory=list)
    exemplar_index: int | None = None  # index of the headline closest to centroid


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Standard cosine similarity. Returns 0.0 when either vector is zero."""
    if len(a) != len(b):
        raise ValueError(
            f"vectors must be same length: {len(a)} vs {len(b)}"
        )
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for ai, bi in zip(a, b):
        dot += ai * bi
        norm_a += ai * ai
        norm_b += bi * bi
    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _normalize(vec: list[float]) -> list[float]:
    norm_sq = sum(v * v for v in vec)
    if norm_sq <= 0:
        return list(vec)
    norm = math.sqrt(norm_sq)
    return [v / norm for v in vec]


def _mean(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i in range(dim):
            out[i] += v[i]
    n = float(len(vectors))
    return [x / n for x in out]


def _kmeans_plus_plus_init(
    embeddings: list[list[float]],
    k: int,
    rng: random.Random,
) -> list[list[float]]:
    """Seed centroids using k-means++ for better convergence than random."""
    if not embeddings:
        return []
    centroids: list[list[float]] = [list(rng.choice(embeddings))]
    while len(centroids) < k:
        # Distance² from each point to its nearest existing centroid.
        dists_sq: list[float] = []
        for v in embeddings:
            best = min((1.0 - cosine_similarity(v, c)) for c in centroids)
            dists_sq.append(max(best, 0.0) ** 2)
        total = sum(dists_sq)
        if total <= 0:
            # All points are duplicates of an existing centroid; bail with a
            # random pick so we don't loop forever.
            centroids.append(list(rng.choice(embeddings)))
            continue
        threshold = rng.random() * total
        cumulative = 0.0
        for i, d in enumerate(dists_sq):
            cumulative += d
            if cumulative >= threshold:
                centroids.append(list(embeddings[i]))
                break
    return centroids


def kmeans(
    embeddings: list[list[float]],
    *,
    k: int,
    max_iter: int = 25,
    seed: int | None = 42,
) -> tuple[list[int], list[list[float]]]:
    """Cosine-distance KMeans.

    Returns:
        (assignments, centroids)
        - assignments[i] = cluster id for embeddings[i].
        - centroids[c] = the (re-normalized) centroid for cluster c.

    Empty input → ([], []). k > N → clamps k to N.
    """
    if not embeddings:
        return ([], [])

    n = len(embeddings)
    k_eff = max(1, min(k, n))
    rng = random.Random(seed)

    centroids = _kmeans_plus_plus_init(embeddings, k_eff, rng)
    assignments = [0] * n

    for _ in range(max_iter):
        new_assignments: list[int] = []
        for v in embeddings:
            best_c = 0
            best_sim = -2.0  # cosine ∈ [-1, 1]
            for ci, c in enumerate(centroids):
                sim = cosine_similarity(v, c)
                if sim > best_sim:
                    best_sim = sim
                    best_c = ci
            new_assignments.append(best_c)
        if new_assignments == assignments:
            break
        assignments = new_assignments

        # Recompute centroids; empty clusters keep their previous centroid
        # (otherwise the algorithm collapses k below k_eff).
        for ci in range(k_eff):
            members = [embeddings[i] for i, a in enumerate(assignments) if a == ci]
            if members:
                centroids[ci] = _normalize(_mean(members))

    return assignments, centroids


def cluster_embeddings(
    embeddings: list[list[float]],
    *,
    k: int = 5,
    seed: int | None = 42,
) -> list[NewsCluster]:
    """Cluster embeddings and pick an exemplar per cluster.

    Exemplar = the embedding with the highest cosine similarity to its
    cluster's centroid; the UI uses this as the headline that "represents"
    the cluster.

    Returns clusters in stable order (cluster_id 0..k-1). Empty clusters
    are still returned (with empty member_indices) so callers can display
    the full grid even when KMeans collapsed a partition.
    """
    assignments, centroids = kmeans(embeddings, k=k, seed=seed)
    out: list[NewsCluster] = []
    for ci in range(len(centroids)):
        members = [i for i, a in enumerate(assignments) if a == ci]
        exemplar: int | None = None
        if members:
            best_sim = -2.0
            for idx in members:
                sim = cosine_similarity(embeddings[idx], centroids[ci])
                if sim > best_sim:
                    best_sim = sim
                    exemplar = idx
        out.append(
            NewsCluster(
                cluster_id=ci,
                member_indices=members,
                exemplar_index=exemplar,
            )
        )
    return out
