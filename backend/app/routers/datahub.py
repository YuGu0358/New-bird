"""DataHub HTTP layer.

Three endpoints:

- ``GET /api/datahub/topics`` — registry inventory (for debugging UIs and the
  command palette).
- ``GET /api/datahub/latest/{topic:path}`` — snapshot read of the cached
  last payload, honoring TTL.
- ``GET /api/datahub/stream/{topic_pattern:path}`` — SSE bridge that
  subscribes the HTTP client to the bus via a glob pattern and streams
  every matching event until disconnect.

Why one combined router rather than reusing `/api/stream`:
the new endpoint takes a glob pattern, not a single topic. We keep the
old `/api/stream/{topic:path}` working (Task 6) for backward compat.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.models.datahub import (
    LatestEventResponse,
    TopicListItem,
    TopicListResponse,
)
from app.services import datahub_service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/datahub", tags=["datahub"])


KEEPALIVE_INTERVAL_SECONDS = 15


# ---------------------------------------------------------------------------
# Inventory + snapshot
# ---------------------------------------------------------------------------


@router.get("/topics", response_model=TopicListResponse)
async def list_topics() -> TopicListResponse:
    items = [
        TopicListItem(
            name=t.name,
            ttl_seconds=t.ttl_seconds,
            throttle_seconds=t.throttle_seconds,
            replay_on_subscribe=t.replay_on_subscribe,
            has_dedupe_fn=t.dedupe_key_fn is not None,
        )
        for t in datahub_service.bus().topics()
    ]
    return TopicListResponse(topics=items)


@router.get(
    "/latest/{topic:path}",
    response_model=LatestEventResponse,
)
async def get_latest(topic: str) -> LatestEventResponse:
    bus = datahub_service.bus()
    if topic not in {t.name for t in bus.topics()}:
        raise HTTPException(status_code=404, detail=f"unknown topic {topic!r}")
    cached = bus.latest(topic)
    if cached is None:
        raise HTTPException(status_code=404, detail=f"no cached event for {topic!r}")
    return LatestEventResponse(topic=topic, payload=cached)


# ---------------------------------------------------------------------------
# SSE bridge
# ---------------------------------------------------------------------------


def _format_sse(topic: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(
        {
            "data": payload,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
        default=str,
    )
    return f"event: {topic}\ndata: {body}\n\n".encode("utf-8")


async def _stream(topic_pattern: str, request: Request) -> AsyncIterator[bytes]:
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def callback(topic: str, payload: dict[str, Any]) -> None:
        await queue.put(_format_sse(topic, payload))

    token = datahub_service.bus().subscribe(topic_pattern, callback)
    try:
        yield b": connected\n\n"
        while True:
            if await request.is_disconnected():
                return
            try:
                chunk = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS
                )
                yield chunk
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        try:
            datahub_service.bus().unsubscribe(token)
        except Exception:  # noqa: BLE001 — bus may already be torn down
            logger.debug("datahub stream: unsubscribe at teardown failed")


@router.get("/stream/{topic_pattern:path}")
async def stream(topic_pattern: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _stream(topic_pattern, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
