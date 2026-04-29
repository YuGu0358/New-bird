"""Server-Sent Events stream endpoint.

Usage:
    EventSource('/api/stream/scheduler:job_completed')

Topics are caller-owned strings - the bus doesn't validate or enumerate
them. We pass topic through `:path` to allow `:` in the topic segment
(e.g. "alerts:triggered") without URL encoding.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.streaming import event_bus

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/stream", tags=["streaming"])


# Send a comment line every 15s so connections stay alive through proxies.
KEEPALIVE_INTERVAL_SECONDS = 15


async def _stream_topic(topic: str, request: Request) -> AsyncIterator[bytes]:
    """Forward bus events to SSE wire format until the client disconnects."""
    queue: asyncio.Queue[str] = asyncio.Queue()

    async def _ingest() -> None:
        async for event in event_bus.subscribe(topic):
            await queue.put(event.to_sse())

    consumer = asyncio.create_task(_ingest(), name=f"sse-ingest-{topic}")
    try:
        # Send an initial comment so the connection is established
        # (browsers don't fire `onopen` until the first byte).
        yield b": connected\n\n"
        while True:
            if await request.is_disconnected():
                return
            try:
                payload = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS
                )
                yield payload.encode("utf-8")
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        consumer.cancel()
        try:
            await consumer
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


@router.get("/{topic:path}/latest")
async def get_latest(topic: str) -> dict[str, Any]:
    """Snapshot read — return the most recent cached event for `topic`.

    Useful for late-joining UI tabs that just want the current state
    without opening an SSE connection. 404 when the cache is empty (or
    the cached value's TTL has expired).

    NOTE: declared BEFORE the catch-all SSE route so FastAPI matches
    `/{topic}/latest` before falling through to `/{topic:path}` (which
    would otherwise greedily swallow the `/latest` suffix into `topic`).
    """
    cached = event_bus.latest(topic)
    if cached is None:
        raise HTTPException(
            status_code=404,
            detail=f"No cached event for topic {topic!r}",
        )
    return {
        "topic": cached.topic,
        "data": cached.data,
        "occurred_at": cached.occurred_at.isoformat(),
    }


@router.get("/{topic:path}")
async def stream_topic(topic: str, request: Request) -> StreamingResponse:
    """Server-Sent Events stream for `topic`.

    Returns `text/event-stream` and never reaches a "complete" state -
    the response stays open until the client disconnects.
    """
    return StreamingResponse(
        _stream_topic(topic, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: don't buffer SSE
        },
    )
