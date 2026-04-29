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
from datetime import datetime, timedelta, timezone
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


@dataclass
class _CachedEvent:
    """Internal — pairs an Event with its expiry instant."""

    event: Event
    expires_at: datetime | None  # None = never expires


class EventBus:
    """Topic -> list[asyncio.Queue] router.

    Subscribers register a queue under their topic of interest; publishers
    fan-out to every queue under that topic. Queues are bounded - if a
    consumer is slow we drop the oldest event for that consumer to keep
    the bus moving.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[Event]]] = {}
        self._latest: dict[str, _CachedEvent] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        topic: str,
        data: dict[str, Any] | None = None,
        *,
        ttl: timedelta | None = None,
    ) -> int:
        """Send `data` to every subscriber on `topic` AND cache as the new
        latest value for the topic. Returns delivery count to live subscribers.

        The cache survives even when no subscribers are listening — that's
        the point of the DataHub upgrade. `ttl` is optional; None means
        no expiry. The cached value is replaced on every publish.

        TTL ONLY governs the cache snapshot returned by `latest()` and the
        `replay_latest=True` branch of `subscribe()`. Live subscribers
        always receive the event regardless of `ttl` — once it's in their
        queue, it will be delivered.
        """
        event = Event(topic=topic, data=dict(data or {}))
        expires_at = (
            event.occurred_at + ttl if ttl is not None else None
        )
        async with self._lock:
            self._latest[topic] = _CachedEvent(event=event, expires_at=expires_at)
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

    def latest(self, topic: str) -> Event | None:
        """Return the most recent cached event for `topic`, honoring TTL.

        Synchronous — reads a dict; we tolerate a benign race with publish()
        because the worst case is "we observed an event 1ms before its
        eviction". TTL eviction is lazy: the entry is removed on the next
        `latest()` call after expiry, NOT on a background sweep.
        """
        cached = self._latest.get(topic)
        if cached is None:
            return None
        if (
            cached.expires_at is not None
            and datetime.now(timezone.utc) >= cached.expires_at
        ):
            # Lazy eviction so the cache is self-trimming under read load.
            self._latest.pop(topic, None)
            return None
        return cached.event

    async def subscribe(
        self,
        topic: str,
        *,
        replay_latest: bool = False,
    ) -> AsyncIterator[Event]:
        """Yield events for `topic` until the consumer cancels.

        Caller pattern:
            async for event in event_bus.subscribe("foo"):
                if some_condition:
                    break

        The async generator handles its own cleanup via try/finally: when
        the caller breaks, raises, or the surrounding task is cancelled,
        the queue is removed from the subscriber list.

        When `replay_latest=True` and a cached value exists for `topic`,
        the iterator yields the cached event as its FIRST event before
        any live events. Lets late-joining consumers see the current
        snapshot without waiting for the next publish.
        """
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_MAXSIZE)
        async with self._lock:
            self._subscribers.setdefault(topic, []).append(queue)
        try:
            if replay_latest:
                cached = self.latest(topic)
                if cached is not None:
                    yield cached
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
        """Test-only - wipe every subscription AND cached value.

        Production code never calls this.
        """
        self._subscribers.clear()
        self._latest.clear()


# Module-level singleton.
event_bus = EventBus()
