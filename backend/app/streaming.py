"""In-process topic-based pub/sub for server-sent events.

Why in-process: the platform runs as a single FastAPI process; a Redis
pub/sub layer would add an ops dependency we don't need at this scale.
If we ever go multi-worker we'll swap the EventBus internals for Redis
without changing callers.

Pattern:
    from app.streaming import event_bus
    await event_bus.publish("scheduler:job_completed", {"job_id": "x"})

    async for event in event_bus.subscribe("scheduler:job_completed"):
        ...

Subscribers each own a bounded queue (max 100 events). When the queue
fills up - typically because the consumer is slow / disconnected - the
oldest event is dropped silently. We don't block publishers on slow
consumers; the publisher contract is "fire and forget".
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

logger = logging.getLogger(__name__)


SUBSCRIBER_QUEUE_MAXSIZE = 100


@dataclass
class Event:
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_sse(self) -> str:
        """Serialize for the SSE wire format.

        Each event becomes:
            event: <topic>
            data: <json payload>
            \n
        SSE requires a blank line as the message terminator. Multi-line
        data must be re-indented with `data:` per line; we keep the
        payload single-line by JSON-encoding it (no newlines).
        """
        payload = json.dumps(
            {"data": self.data, "occurred_at": self.occurred_at.isoformat()},
            default=str,
        )
        return f"event: {self.topic}\ndata: {payload}\n\n"


class EventBus:
    """Topic -> list[asyncio.Queue] router.

    Subscribers register a queue under their topic of interest; publishers
    fan-out to every queue under that topic. Queues are bounded - if a
    consumer is slow we drop the oldest event for that consumer to keep
    the bus moving.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, data: dict[str, Any] | None = None) -> int:
        """Send `data` to every subscriber on `topic`. Returns delivery count."""
        event = Event(topic=topic, data=dict(data or {}))
        async with self._lock:
            queues = list(self._subscribers.get(topic, ()))
        delivered = 0
        for queue in queues:
            try:
                queue.put_nowait(event)
                delivered += 1
            except asyncio.QueueFull:
                # Slow consumer - drop oldest then enqueue. We accept the
                # write race here; queue is per-subscriber so the only
                # contention is between the bus and that one consumer.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                    delivered += 1
                except asyncio.QueueFull:
                    logger.debug(
                        "EventBus: dropping event on full queue (topic=%s)", topic
                    )
        return delivered

    async def subscribe(self, topic: str) -> AsyncIterator[Event]:
        """Yield events for `topic` until the consumer cancels.

        Caller pattern:
            async for event in event_bus.subscribe("foo"):
                if some_condition:
                    break

        The async generator handles its own cleanup via try/finally: when
        the caller breaks, raises, or the surrounding task is cancelled,
        the queue is removed from the subscriber list.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            async with self._lock:
                bucket = self._subscribers.get(topic)
                if bucket is not None:
                    try:
                        bucket.remove(queue)
                    except ValueError:
                        pass
                    if not bucket:
                        self._subscribers.pop(topic, None)

    def subscriber_count(self, topic: str) -> int:
        """Test/observability helper - how many active queues on topic."""
        return len(self._subscribers.get(topic, ()))

    def reset(self) -> None:
        """Test-only - wipe every subscription. Production code never calls this."""
        self._subscribers.clear()


# Module-level singleton.
event_bus = EventBus()
