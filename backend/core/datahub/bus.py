"""DataHub bus — in-process topic-based pub/sub.

Design notes:

- Every publish is fire-and-forget for the publisher: we schedule each
  callback on a fresh asyncio.Task so a slow / hung callback can't block
  the publisher or other subscribers.
- Glob patterns are evaluated at publish time. Subscribers store their
  literal pattern; for each publish we walk the subscriber list and run
  `pattern_matches(pattern, topic)`. This is O(N_subscribers) per publish
  but N is tiny (one per SSE client + a handful of in-process
  consumers); a bucketed index would be premature optimization.
- Topic registration is required before publish. Unregistered publishes
  raise rather than silently dropping — better to fail loudly during
  service wiring than to debug a missing producer at 3am.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.datahub.errors import SubscriberClosedError, UnknownTopicError
from core.datahub.matching import pattern_matches
from core.datahub.topic import Topic

logger = logging.getLogger(__name__)


SubscriberCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


# Indirection so tests can monkeypatch the clock without touching time.monotonic
# globally (which would affect asyncio internals).
def _monotonic() -> float:
    return time.monotonic()


_SENTINEL: Any = object()


@dataclass(frozen=True)
class SubscriptionToken:
    """Opaque handle returned by `subscribe()`. Pass back to `unsubscribe()`."""

    token_id: str


@dataclass
class _Subscription:
    pattern: str
    callback: SubscriberCallback
    token: SubscriptionToken


@dataclass
class _TopicState:
    """Per-topic mutable state — TTL cache, dedupe key, throttle clock."""

    topic: Topic
    last_payload: dict[str, Any] | None = None
    last_published_at: float | None = None  # monotonic, for throttle
    last_payload_at: float | None = None  # monotonic, for TTL
    last_dedupe_key: Any = field(default=_SENTINEL)


class Bus:
    """In-process topic-based pub/sub.

    Public API:
        register(topic)
        subscribe(pattern, callback) -> SubscriptionToken
        unsubscribe(token)
        publish(topic_name, payload) -> int (count of dispatched callbacks)
        latest(topic_name) -> dict | None

    All async methods are safe to call concurrently from any task.
    """

    def __init__(self) -> None:
        self._topics: dict[str, _TopicState] = {}
        self._subscriptions: dict[str, _Subscription] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, topic: Topic) -> None:
        """Idempotently register a `Topic`.

        Re-registering with the same name OVERWRITES the previous policy.
        This is intentional — it lets lifespan re-registration tolerate
        partial earlier wiring.
        """
        self._topics[topic.name] = _TopicState(topic=topic)

    def topics(self) -> list[Topic]:
        """Snapshot of every registered Topic. Used by the inventory route."""
        return [state.topic for state in self._topics.values()]

    # ------------------------------------------------------------------
    # subscribe / unsubscribe (with replay)
    # ------------------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        callback: SubscriberCallback,
    ) -> SubscriptionToken:
        """Register `callback` for every topic matching `pattern`.

        `pattern` is a glob — exact name like `market:quote:SPY` matches
        only that topic; `market:quote:*` matches every quote topic.
        The callback runs in its own Task per-publish; exceptions inside
        it are logged and swallowed.

        When a matching topic has `replay_on_subscribe=True` and a
        non-expired cached payload, the callback receives that snapshot
        as its first event before any live events.
        """
        token = SubscriptionToken(token_id=uuid.uuid4().hex)
        self._subscriptions[token.token_id] = _Subscription(
            pattern=pattern, callback=callback, token=token
        )
        # Replay cached snapshots from every matching topic that has
        # replay_on_subscribe=True and a non-expired cached payload.
        for state in self._topics.values():
            if not state.topic.replay_on_subscribe:
                continue
            if not pattern_matches(pattern, state.topic.name):
                continue
            cached = self._read_replay(state)
            if cached is None:
                continue
            asyncio.create_task(
                self._safe_invoke(callback, state.topic.name, cached),
                name=f"datahub-replay-{token.token_id[:8]}",
            )
        return token

    def unsubscribe(self, token: SubscriptionToken) -> None:
        """Drop the subscription. Idempotency is NOT promised — calling
        twice raises so accidental double-cleanup is visible."""
        if token.token_id not in self._subscriptions:
            raise SubscriberClosedError(f"token {token.token_id!r} unknown")
        del self._subscriptions[token.token_id]

    def subscriber_count(self, topic_name: str) -> int:
        """Test/observability helper — how many live subscriptions match
        `topic_name` (post-glob expansion)."""
        return sum(
            1
            for sub in self._subscriptions.values()
            if pattern_matches(sub.pattern, topic_name)
        )

    @staticmethod
    def _read_replay(state: _TopicState) -> dict[str, Any] | None:
        if state.last_payload is None or state.last_payload_at is None:
            return None
        ttl = state.topic.ttl_seconds
        if ttl is not None and (_monotonic() - state.last_payload_at) >= ttl:
            return None
        return state.last_payload

    # ------------------------------------------------------------------
    # publish (with dedupe + throttle + TTL cache write)
    # ------------------------------------------------------------------

    async def publish(self, topic_name: str, payload: dict[str, Any]) -> int:
        """Publish `payload` on `topic_name`.

        Returns the number of subscriber callbacks that were dispatched
        (i.e. matched the topic). A return of 0 with no exception means
        the topic was registered but no live subscribers matched, OR the
        publish was throttled / deduped.
        """
        state = self._topics.get(topic_name)
        if state is None:
            raise UnknownTopicError(
                f"topic {topic_name!r} not registered; "
                f"call Bus.register() during service startup"
            )

        # 1. throttle gate
        if state.topic.throttle_seconds > 0 and state.last_published_at is not None:
            elapsed = _monotonic() - state.last_published_at
            if elapsed < state.topic.throttle_seconds:
                return 0

        # 2. dedupe gate
        if state.topic.dedupe_key_fn is not None:
            key = state.topic.dedupe_key_fn(payload)
            if state.last_dedupe_key is not _SENTINEL and key == state.last_dedupe_key:
                return 0
            state.last_dedupe_key = key

        # 3. cache write — for replay
        now = _monotonic()
        state.last_payload = dict(payload)
        state.last_payload_at = now
        state.last_published_at = now

        # 4. fan-out
        matches = [
            sub
            for sub in self._subscriptions.values()
            if pattern_matches(sub.pattern, topic_name)
        ]
        for sub in matches:
            asyncio.create_task(
                self._safe_invoke(sub.callback, topic_name, payload),
                name=f"datahub-cb-{sub.token.token_id[:8]}",
            )
        return len(matches)

    @staticmethod
    async def _safe_invoke(
        cb: SubscriberCallback, topic: str, payload: dict[str, Any]
    ) -> None:
        try:
            await cb(topic, payload)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — bus must outlive bad callbacks
            logger.exception("datahub: subscriber callback failed (topic=%s)", topic)

    # ------------------------------------------------------------------
    # latest snapshot read (synchronous, public)
    # ------------------------------------------------------------------

    def latest(self, topic_name: str) -> dict[str, Any] | None:
        """Return the most recent cached payload for `topic_name`, honoring
        TTL. Returns None when nothing has been published OR when the cache
        has expired. Used by the snapshot endpoint."""
        state = self._topics.get(topic_name)
        if state is None:
            return None
        return self._read_replay(state)
