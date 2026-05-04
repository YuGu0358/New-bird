"""DEPRECATED — single-topic EventBus shim.

Phase 6.1 split:

- The module-level ``event_bus`` symbol is now a *shim* that forwards
  to ``app.services.datahub_service`` so any pre-migration import of
  ``from app.streaming import event_bus`` keeps working but the bytes
  flow through the canonical DataHub pub/sub.
- The original ``EventBus`` / ``Event`` classes are retained for legacy
  tests and any caller that still constructs its own bus instance —
  they remain pure-Python with no datahub dependency. New code should
  not depend on them; removal target Phase 6.2.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from app.services import datahub_service
from core.datahub import Topic, UnknownTopicError

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
    """DEPRECATED legacy single-topic bus. New code: use DataHub.

    Topic -> list[asyncio.Queue] router. Subscribers register a queue
    under their topic of interest; publishers fan-out to every queue
    under that topic. Queues are bounded - if a consumer is slow we
    drop the oldest event for that consumer to keep the bus moving.
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
        cached = self._latest.get(topic)
        if cached is None:
            return None
        if (
            cached.expires_at is not None
            and datetime.now(timezone.utc) >= cached.expires_at
        ):
            self._latest.pop(topic, None)
            return None
        return cached.event

    async def subscribe(
        self,
        topic: str,
        *,
        replay_latest: bool = False,
    ) -> AsyncIterator[Event]:
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
        return len(self._subscribers.get(topic, ()))

    def reset(self) -> None:
        """Test-only - wipe every subscription AND cached value."""
        self._subscribers.clear()
        self._latest.clear()


class _LegacyEventBusShim:
    """Translates legacy short topic names (`quote:SPY`) into canonical
    DataHub names (`market:quote:SPY`).

    This is the object exposed as the module-level ``event_bus`` symbol.
    Pre-migration callers calling ``await event_bus.publish(...)`` will
    keep working while the bytes flow through the DataHub bus.
    """

    @staticmethod
    def _canonical(name: str) -> str:
        if name.startswith("quote:"):
            return "market:" + name
        return name

    async def publish(
        self,
        topic: str,
        data: dict[str, Any] | None = None,
        **_: Any,
    ) -> int:
        canonical = self._canonical(topic)
        bus = datahub_service.bus()
        if canonical not in {t.name for t in bus.topics()}:
            datahub_service.register_topic(Topic(name=canonical, ttl_seconds=60.0))
        try:
            return await datahub_service.publish(canonical, dict(data or {}))
        except UnknownTopicError:
            return 0

    def reset(self) -> None:
        """Compatibility shim — resetting the legacy bus is a no-op now;
        the DataHub singleton owns its own lifecycle via
        ``datahub_service.shutdown()``. Tests that called this on the
        legacy global still get a clean call."""
        return None


event_bus = _LegacyEventBusShim()
