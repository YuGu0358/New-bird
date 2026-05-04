"""Legacy SSE bridge — forwards to the new DataHub bus.

DEPRECATED. New code MUST use `/api/datahub/stream/{topic_pattern:path}`.

Behaviour preserved for the transition window:

- ``GET /api/stream/{topic:path}`` accepts a single topic (no glob).
- The legacy topic taxonomy used short names (`quote:SPY`); we map to
  the new `market:quote:SPY` form before subscribing.
- ``GET /api/stream/{topic:path}/latest`` keeps returning the cached
  snapshot (now read from the DataHub bus).

Removal target: Phase 6.2 once the frontend migrates.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.services import datahub_service

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/stream", tags=["streaming"])


KEEPALIVE_INTERVAL_SECONDS = 15


def _to_new_name(legacy: str) -> str:
    """Map old short topic names to canonical taxonomy.

    Phase 6.1 only knows one legacy mapping; new short names should not
    be added here — emit on the canonical name instead.
    """
    if legacy.startswith("quote:"):
        return "market:" + legacy
    return legacy  # pass-through for already-canonical names


def _format_sse(topic: str, payload: dict[str, Any]) -> bytes:
    body = json.dumps(
        {
            "data": payload,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        },
        default=str,
    )
    return f"event: {topic}\ndata: {body}\n\n".encode("utf-8")


async def _stream(legacy_topic: str, request: Request) -> AsyncIterator[bytes]:
    canonical = _to_new_name(legacy_topic)
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def callback(topic: str, payload: dict[str, Any]) -> None:
        await queue.put(_format_sse(legacy_topic, payload))

    token = datahub_service.bus().subscribe(canonical, callback)
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
        except Exception:  # noqa: BLE001
            logger.debug("legacy stream: unsubscribe at teardown failed")


@router.get("/{topic:path}/latest")
async def get_latest(topic: str) -> dict[str, Any]:
    canonical = _to_new_name(topic)
    bus = datahub_service.bus()
    if canonical not in {t.name for t in bus.topics()}:
        raise HTTPException(status_code=404, detail=f"no cached event for {topic!r}")
    cached = bus.latest(canonical)
    if cached is None:
        raise HTTPException(status_code=404, detail=f"no cached event for {topic!r}")
    return {
        "topic": topic,
        "data": cached,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/{topic:path}")
async def stream_topic(topic: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _stream(topic, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
