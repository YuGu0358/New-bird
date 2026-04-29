"""News clustering service — Tavily headlines × OpenAI embeddings → topic groups.

Pulls raw headlines via the existing tavily_service path, embeds each title
through OpenAI's text-embedding-3-small, and runs the pure-compute KMeans
helper to bundle them into k topic clusters. The exemplar headline closest
to each centroid becomes the cluster label-source.

Why no separate cluster-naming LLM call: the exemplar title is itself the
shortest, most-information-dense human label we can get, and skipping a
second LLM round-trip keeps p95 below 1s for a typical 12-headline pull.
A future task can layer "summarize this cluster in 3 words" on top.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import runtime_settings
from app.services import openai_service, tavily_service
from app.services.network_utils import run_sync_with_retries
from core.news_clustering import cluster_embeddings

logger = logging.getLogger(__name__)


_EMBEDDING_MODEL_KEY = "OPENAI_EMBEDDING_MODEL"
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


def _embed_blocking(texts: list[str]) -> list[list[float]]:
    """Batch-embed a list of strings via OpenAI's embeddings endpoint."""
    if not texts:
        return []
    client = openai_service.create_client()
    model = (
        runtime_settings.get_setting(_EMBEDDING_MODEL_KEY, _DEFAULT_EMBEDDING_MODEL)
        or _DEFAULT_EMBEDDING_MODEL
    )
    response = client.embeddings.create(model=model, input=texts)
    # OpenAI guarantees the order matches the input; embeddings already
    # arrive L2-normalized for the v3 family but we don't rely on that.
    return [list(item.embedding) for item in response.data]


async def cluster_headlines(
    symbol: str,
    *,
    max_results: int = 12,
    k_clusters: int = 4,
    lang: str = "en",
) -> dict[str, Any]:
    """Fetch raw headlines for `symbol` and group them into `k_clusters` topics.

    Returns a payload shaped for the response model: clusters, each with
    exemplar title + member headlines, plus the underlying raw list.
    """
    if not openai_service.is_configured():
        raise RuntimeError(
            "OPENAI_API_KEY is missing — news clustering needs embeddings. "
            "Configure it in the settings page first."
        )

    headlines_payload = await tavily_service.fetch_raw_headlines(
        symbol, max_results=max_results, lang=lang
    )
    headlines: list[dict[str, Any]] = list(headlines_payload.get("headlines") or [])
    if not headlines:
        return {
            "symbol": headlines_payload["symbol"],
            "k_clusters": 0,
            "clusters": [],
            "headlines": [],
            "generated_at": datetime.now(timezone.utc),
        }

    titles = [str(h.get("title") or h.get("url") or "") for h in headlines]
    embeddings = await run_sync_with_retries(_embed_blocking, titles)

    if not embeddings:
        # Embedding API failed entirely — surface the headlines as a single
        # "unclustered" bucket rather than 502'ing on the user.
        logger.debug("News clustering: embeddings empty, returning single bucket")
        return {
            "symbol": headlines_payload["symbol"],
            "k_clusters": 1,
            "clusters": [
                {
                    "cluster_id": 0,
                    "exemplar_title": titles[0],
                    "size": len(titles),
                    "member_indices": list(range(len(titles))),
                }
            ],
            "headlines": headlines,
            "generated_at": datetime.now(timezone.utc),
        }

    clusters = cluster_embeddings(embeddings, k=k_clusters, seed=42)

    cluster_payload: list[dict[str, Any]] = []
    for cluster in clusters:
        exemplar_title = (
            titles[cluster.exemplar_index]
            if cluster.exemplar_index is not None
            else None
        )
        cluster_payload.append(
            {
                "cluster_id": cluster.cluster_id,
                "exemplar_title": exemplar_title,
                "size": len(cluster.member_indices),
                "member_indices": list(cluster.member_indices),
            }
        )
    # Order non-empty clusters first, then by size descending — UX wants the
    # densest topic at the top.
    cluster_payload.sort(key=lambda c: (-int(c["size"]), int(c["cluster_id"])))

    return {
        "symbol": headlines_payload["symbol"],
        "k_clusters": len([c for c in cluster_payload if c["size"] > 0]),
        "clusters": cluster_payload,
        "headlines": headlines,
        "generated_at": datetime.now(timezone.utc),
    }
