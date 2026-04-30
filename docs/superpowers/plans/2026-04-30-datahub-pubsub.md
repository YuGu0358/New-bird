# Phase 6.1 — DataHub Pub/Sub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the ad-hoc per-service publishers (Polygon WS, social signal, sector rotation, AI Council, etc.) with a unified internal **topic-based pub/sub** that has a stable topic taxonomy (`market:quote:{sym}` / `market:trade:{sym}` / `broker:{name}:positions` / `macro:fred:{code}` / `signal:{sym}:{kind}` / `agent:verdict:{persona}:{sym}`), per-topic TTL + dedupe + throttle policy, glob-style subscriptions, and a single SSE bridge. After Phase 6.1 is in place, every Phase 5/6/7 producer (visual workflow nodes, AI Council, MCP tools, alert engine) plugs into the same backbone instead of growing more direct fan-out wiring.

**Architecture:** A pure-Python `Bus` lives under `backend/core/datahub/` (no FastAPI, no global state, no `asyncio` pre-binding) so it is unit-testable in isolation and can be reused by `core/workflow/` later. The FastAPI integration layer is `backend/app/services/datahub_service.py`, which owns the process-singleton `Bus` instance, performs lifespan registration, and holds the producer↔consumer wiring (Polygon WS publisher, scheduled-job emitters). A topic-aware SSE router replaces the existing `/api/stream` endpoint with `/api/datahub/stream/{topic_pattern:path}` — old `/api/stream/...` continues to work via a thin shim that forwards to the bus, so frontend code can migrate incrementally.

The bus is deliberately **in-process** at this phase. We do not introduce Redis or NATS; the platform runs as one FastAPI worker. If we ever scale horizontally, the `Bus` interface is small enough (`subscribe`, `unsubscribe`, `publish`) that a Redis-backed implementation can drop in behind the same calls.

**Tech Stack:** Python 3.11, `asyncio`, `dataclasses`, `fnmatch` (glob matching from stdlib — no third-party dep), FastAPI, pytest, pytest-asyncio. No new packages required. We reuse the existing async-SQLAlchemy + APScheduler stack only insofar as the existing producers (e.g. scheduled jobs that already emit social signals) can route their existing payloads through the bus.

---

## File Structure

**Create:**

- `backend/core/datahub/__init__.py` — package marker; re-exports `Bus`, `Topic`, `SubscriptionToken`, `BusPublishOutcome`. ~15 LOC.
- `backend/core/datahub/topic.py` — `Topic` frozen dataclass (`name`, `ttl_seconds`, `dedupe_key_fn`, `throttle_seconds`, `replay_on_subscribe`). ~60 LOC.
- `backend/core/datahub/matching.py` — pure helpers: `pattern_matches(pattern: str, topic: str) -> bool` and `is_glob_pattern(s: str) -> bool`. Wraps `fnmatch` with the colon-segment semantics our taxonomy uses. ~50 LOC.
- `backend/core/datahub/bus.py` — `Bus` class with `subscribe`, `unsubscribe`, `publish`, plus internal `_TopicState` value object holding TTL cache, last dedupe key, last published instant. ~280 LOC.
- `backend/core/datahub/errors.py` — `BusError`, `UnknownTopicError`, `SubscriberClosedError`. ~30 LOC.
- `backend/app/services/datahub_service.py` — process-level singleton accessor + lifespan hooks `start()` / `shutdown()`; pre-registers default topics from the taxonomy; wires Polygon WS publisher into the bus. ~180 LOC.
- `backend/app/routers/datahub.py` — `GET /api/datahub/topics` (registry inventory), `GET /api/datahub/stream/{topic_pattern:path}` (SSE bridge), `GET /api/datahub/latest/{topic:path}` (snapshot). ~150 LOC.
- `backend/app/models/datahub.py` — Pydantic response schemas: `TopicListItem`, `TopicListResponse`, `LatestEventResponse`. ~50 LOC.
- `backend/tests/test_datahub_bus.py` — unit tests for `Bus` (subscribe/publish/unsubscribe, glob matching, TTL replay, dedupe, throttle, slow-consumer drop). ~520 LOC.
- `backend/tests/test_datahub_service.py` — service-layer tests (singleton accessor, default topic registration, Polygon WS payload reaches bus). ~220 LOC.
- `backend/tests/test_datahub_router.py` — endpoint tests (topics inventory, latest snapshot, SSE bridge end-to-end). ~260 LOC.

**Modify:**

- `backend/app/main.py` — lifespan calls `datahub_service.start()` BEFORE `polygon_ws_publisher.start()` and `datahub_service.shutdown()` AFTER `polygon_ws_publisher.shutdown()`; mount `routers/datahub.py`.
- `backend/app/services/polygon_ws_publisher.py` — `_publish_tick` calls `datahub_service.publish("market:quote:{sym}", payload)` instead of `event_bus.publish("quote:{sym}", payload)`.
- `backend/app/streaming.py` — keep the legacy `event_bus` symbol as a thin shim that forwards to `datahub_service.bus()` so any caller that was not yet migrated continues to work.
- `backend/app/routers/stream.py` — re-implement as a forwarder over `datahub_service.bus().subscribe(...)` so legacy URLs still stream; mark the file with a `DEPRECATED` block-level docstring pointing to the new router.
- `backend/tests/test_openapi_parity.py` — add `("GET", "/api/datahub/topics")`, `("GET", "/api/datahub/latest/{topic:path}")`, `("GET", "/api/datahub/stream/{topic_pattern:path}")`.

**Out of scope for this plan (handled in 6.2 / 6.3 / later phases):**

- Frontend rewrite to consume the new pattern-style SSE URLs (`/api/datahub/stream/market:quote:*`). The existing `/api/stream/quote:SPY` URLs keep working.
- Redis or external broker backend.
- Persisting topics across restarts (the registry is rebuilt at lifespan startup from the canonical topic-taxonomy config).
- Wiring AI Council verdicts (`agent:verdict:*`) onto the bus — that lands in the AI Council Phase 7 follow-up; the topic class is registered as a placeholder so consumers can subscribe early.
- Multi-process pub/sub. Single-process happy path only.

---

## Reference: Existing Code to Read Before Starting

Read these files once at the top; tasks below will not re-explain them.

1. `backend/app/streaming.py` lines 1–208 — the current single-topic `EventBus`. Our new `Bus` is the superset; we are **not** deleting this file in Phase 6.1, only re-pointing `event_bus` at the new bus via a shim.
2. `backend/app/routers/stream.py` lines 1–101 — current SSE endpoint. We model the new SSE bridge on this exact shape (`KEEPALIVE_INTERVAL_SECONDS = 15`, initial `: connected\n\n` byte, `X-Accel-Buffering: no` header, `is_disconnected()` polling).
3. `backend/app/services/polygon_ws_publisher.py` lines 1–192 — the producer we migrate. Note `_publish_tick` is the only place that touches `event_bus`; everything else is reconnect bookkeeping.
4. `backend/app/services/scheduled_jobs.py` lines 1–177 — pattern for periodic publishers (we will reuse this style when Phase 6.1 follow-ups wire `macro:fred:*` and `broker:*:positions` jobs through the bus, but we DO NOT migrate them in this plan).
5. `backend/app/main.py` lines 78–119 — lifespan ordering. The bus must start BEFORE Polygon WS (so the WS publisher's first publish has a registered topic) and shut down AFTER (so we drain in-flight ticks).
6. `backend/app/scheduler.py` — singleton pattern with `_lock = asyncio.Lock()`, `start()` / `shutdown()` idempotency. We mirror its public-surface conventions in `datahub_service`.
7. `backend/tests/conftest.py` — pytest fixtures + asyncio_mode. New tests must work under both `pytest` and stdlib `unittest discover` (CI runs the latter).
8. `backend/tests/test_openapi_parity.py` lines 130–145 — pattern for adding new endpoints to the parity list; copy the same tuple shape.
9. `CLAUDE.md` — async-everywhere, runtime_settings (not `os.environ` for keys), `core/` is provider-agnostic, `services/` orchestrates.

Topic taxonomy (canonical names — used verbatim by every task that registers a topic):

| Pattern | Producer (today / future) | TTL | Throttle | Dedupe key |
|---|---|---|---|---|
| `market:quote:{sym}` | Polygon WS publisher | 60s | 0s (forward every tick) | `(price, timestamp)` |
| `market:trade:{sym}` | Polygon WS publisher (future) | 60s | 0s | `trade_id` |
| `broker:{name}:positions` | Phase 2.4 IBKR sync (future) | 5min | 60s | `(account, hash(positions))` |
| `macro:fred:{code}` | Phase 4.1 macro_sync (future) | 24h | 60s | `release_date` |
| `signal:{sym}:{kind}` | Social signal pipeline (future) | 15min | 5s | `(sym, kind, value)` |
| `agent:verdict:{persona}:{sym}` | AI Council (future) | 1h | 5s | `(persona, sym, verdict_id)` |

Phase 6.1 only **wires** `market:quote:*`. The other patterns are **registered** so consumers can subscribe and receive `replay_latest` snapshots when the future producers come online.

---

## Tasks

### Task 1: `Topic` value object + glob pattern matching

**Files:**
- Create: `backend/core/datahub/__init__.py`
- Create: `backend/core/datahub/topic.py`
- Create: `backend/core/datahub/matching.py`
- Create: `backend/core/datahub/errors.py`
- Create: `backend/tests/test_datahub_bus.py` (we begin the test file; later tasks append to it)

**Why this comes first:** every later task references `Topic` and `pattern_matches`. They are pure (no asyncio, no FastAPI); we get them green before touching the bus.

- [ ] **Step 1: Write the failing test for `Topic` defaults and immutability**

Create `backend/tests/test_datahub_bus.py`:

```python
"""DataHub bus + topic + matching unit tests.

Pure-compute layer — no FastAPI, no asyncio.create_task at module import,
no DB. Each test constructs a fresh Bus to avoid singleton pollution.
"""
from __future__ import annotations

import asyncio
import dataclasses
import pytest

from core.datahub import Topic
from core.datahub.matching import pattern_matches, is_glob_pattern


# ---------- Topic ----------------------------------------------------------


def test_topic_has_sane_defaults() -> None:
    # Arrange / Act
    topic = Topic(name="market:quote:SPY")

    # Assert
    assert topic.name == "market:quote:SPY"
    assert topic.ttl_seconds is None
    assert topic.throttle_seconds == 0.0
    assert topic.replay_on_subscribe is False
    assert topic.dedupe_key_fn is None


def test_topic_is_frozen() -> None:
    topic = Topic(name="market:quote:SPY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        topic.ttl_seconds = 60  # type: ignore[misc]
```

Run from `backend/`:

```bash
pytest tests/test_datahub_bus.py::test_topic_has_sane_defaults -x
```

Expected: `ModuleNotFoundError: No module named 'core.datahub'`. Good — RED.

- [ ] **Step 2: Implement `Topic`**

Create `backend/core/datahub/topic.py`:

```python
"""Topic value object — immutable per-topic config.

A `Topic` describes ONE stable channel name and the policy applied when
publishing into it: time-to-live for the cached "latest" snapshot,
dedupe-key extraction, and throttle window. Producers and consumers both
look up a topic by name through the `Bus`; the `Topic` itself is a pure
config record with no behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional


DedupeKeyFn = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class Topic:
    """Per-channel publication policy.

    Attributes:
        name: Canonical topic name. Use the colon-segment taxonomy:
            `domain:kind:specifier`, e.g. `market:quote:SPY`.
        ttl_seconds: How long the last-published payload is retained in
            the bus' replay cache. ``None`` means "never expire". Live
            subscribers always receive every event regardless of TTL —
            this only governs `replay_latest`.
        throttle_seconds: Minimum gap between two accepted publishes on
            this topic. ``0`` disables throttling (every publish goes
            through). Throttled publishes are dropped silently.
        replay_on_subscribe: When True, a new subscriber receives the
            cached last event (if any, and TTL has not expired) as its
            first event before any live events.
        dedupe_key_fn: Optional callable that extracts a hashable dedupe
            key from a payload. When two consecutive publishes produce
            the SAME key, the second is dropped. ``None`` disables
            dedupe.
    """

    name: str
    ttl_seconds: Optional[float] = None
    throttle_seconds: float = 0.0
    replay_on_subscribe: bool = False
    dedupe_key_fn: Optional[DedupeKeyFn] = None
```

Create `backend/core/datahub/errors.py`:

```python
"""DataHub exception hierarchy."""
from __future__ import annotations


class BusError(Exception):
    """Base for every DataHub failure."""


class UnknownTopicError(BusError):
    """Raised when a publish targets a topic that was never registered."""


class SubscriberClosedError(BusError):
    """Raised when an already-unsubscribed token is unsubscribed again."""
```

Create `backend/core/datahub/__init__.py`:

```python
"""DataHub: in-process topic-based pub/sub.

Pure-compute package — depends only on stdlib `asyncio`, `dataclasses`,
`fnmatch`. Importable from any layer without pulling in FastAPI.
"""
from __future__ import annotations

from core.datahub.errors import (
    BusError,
    SubscriberClosedError,
    UnknownTopicError,
)
from core.datahub.topic import DedupeKeyFn, Topic

__all__ = [
    "BusError",
    "DedupeKeyFn",
    "SubscriberClosedError",
    "Topic",
    "UnknownTopicError",
]
```

Re-run:

```bash
pytest tests/test_datahub_bus.py::test_topic_has_sane_defaults -x
pytest tests/test_datahub_bus.py::test_topic_is_frozen -x
```

Expected: both PASS. GREEN.

- [ ] **Step 3: Write failing tests for `pattern_matches` and `is_glob_pattern`**

Append to `backend/tests/test_datahub_bus.py`:

```python
# ---------- matching -------------------------------------------------------


@pytest.mark.parametrize(
    "pattern,topic,expected",
    [
        # Exact match (no glob characters)
        ("market:quote:SPY", "market:quote:SPY", True),
        ("market:quote:SPY", "market:quote:AAPL", False),

        # Single-segment wildcard
        ("market:quote:*", "market:quote:SPY", True),
        ("market:quote:*", "market:quote:AAPL", True),
        ("market:quote:*", "market:trade:SPY", False),

        # Multi-segment wildcard via `*` (fnmatch treats * greedy across `:`)
        ("market:*", "market:quote:SPY", True),
        ("market:*", "market:trade:SPY", True),
        ("market:*", "broker:ibkr:positions", False),

        # `?` single char
        ("market:quote:SP?", "market:quote:SPY", True),
        ("market:quote:SP?", "market:quote:SPYY", False),

        # Empty / pathological
        ("", "", True),
        ("market:quote:SPY", "", False),
    ],
)
def test_pattern_matches(pattern: str, topic: str, expected: bool) -> None:
    assert pattern_matches(pattern, topic) is expected


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("market:quote:*", True),
        ("market:quote:SP?", True),
        ("market:quote:[ABC]", True),
        ("market:quote:SPY", False),
        ("", False),
    ],
)
def test_is_glob_pattern(candidate: str, expected: bool) -> None:
    assert is_glob_pattern(candidate) is expected
```

Run:

```bash
pytest tests/test_datahub_bus.py -k "pattern_matches or is_glob_pattern" -x
```

Expected: import error on `core.datahub.matching`. RED.

- [ ] **Step 4: Implement `matching`**

Create `backend/core/datahub/matching.py`:

```python
"""Glob-style topic matching.

Why fnmatch and not regex: our taxonomy uses colon-segment names
(`market:quote:SPY`) and the only wildcard semantics we need are `*`
(any chars including colon — matches "everything below this level"),
`?` (any single char), and `[seq]`. fnmatch from stdlib gives us all
three with predictable behaviour and no engine-flavour drift.

Subtlety: in our taxonomy, `market:quote:*` is intuitively expected to
match `market:quote:SPY` but NOT `market:quote:SPY:extra`. Today we
DO NOT enforce that — `*` is greedy across `:`. If the future taxonomy
grows a fourth segment we revisit; the current registered topics are
all 2- or 3-segment, so this is fine.
"""
from __future__ import annotations

import fnmatch


_GLOB_CHARS = ("*", "?", "[")


def pattern_matches(pattern: str, topic: str) -> bool:
    """Return True iff `topic` matches the glob `pattern`.

    Exact-string equality short-circuits before fnmatch so callers that
    pass non-glob topic names pay no regex-compile cost.
    """
    if not any(c in pattern for c in _GLOB_CHARS):
        return pattern == topic
    return fnmatch.fnmatchcase(topic, pattern)


def is_glob_pattern(candidate: str) -> bool:
    """True iff `candidate` contains a glob metacharacter.

    Used by the SSE router to decide whether to subscribe to one topic
    or to a wildcard pattern.
    """
    return any(c in candidate for c in _GLOB_CHARS)
```

Re-run:

```bash
pytest tests/test_datahub_bus.py -k "pattern_matches or is_glob_pattern" -x
```

Expected: 13 passed. GREEN.

- [ ] **Step 5: Commit**

```bash
git add backend/core/datahub/__init__.py backend/core/datahub/topic.py backend/core/datahub/matching.py backend/core/datahub/errors.py backend/tests/test_datahub_bus.py
git commit -m "feat(datahub): Topic value object + glob pattern matching"
```

---

### Task 2: `Bus` core — register, subscribe, publish, unsubscribe

**Files:**
- Create: `backend/core/datahub/bus.py`
- Modify: `backend/core/datahub/__init__.py`
- Modify: `backend/tests/test_datahub_bus.py`

- [ ] **Step 1: Write the failing tests for register + subscribe + publish + unsubscribe**

Append to `backend/tests/test_datahub_bus.py`:

```python
# ---------- Bus registration & subscribe/publish/unsubscribe --------------


from core.datahub import Bus, SubscriberClosedError, UnknownTopicError


@pytest.mark.asyncio
async def test_bus_publish_to_unregistered_topic_raises() -> None:
    bus = Bus()
    with pytest.raises(UnknownTopicError):
        await bus.publish("market:quote:SPY", {"price": 100.0})


@pytest.mark.asyncio
async def test_bus_register_and_publish_to_one_subscriber() -> None:
    # Arrange
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    received: list[dict] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append({"topic": topic, "payload": payload})

    token = bus.subscribe("market:quote:SPY", callback)

    # Act
    delivered = await bus.publish("market:quote:SPY", {"price": 410.5})
    # Yield once so the callback task runs.
    await asyncio.sleep(0)

    # Assert
    assert delivered == 1
    assert received == [{"topic": "market:quote:SPY", "payload": {"price": 410.5}}]

    # Cleanup
    bus.unsubscribe(token)


@pytest.mark.asyncio
async def test_bus_subscribe_via_glob_pattern_fans_out() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    bus.register(Topic(name="market:quote:AAPL"))
    received: list[str] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append(topic)

    token = bus.subscribe("market:quote:*", callback)
    await bus.publish("market:quote:SPY", {"price": 1.0})
    await bus.publish("market:quote:AAPL", {"price": 2.0})
    await asyncio.sleep(0)

    assert sorted(received) == ["market:quote:AAPL", "market:quote:SPY"]
    bus.unsubscribe(token)


@pytest.mark.asyncio
async def test_bus_unsubscribe_stops_delivery() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    received: list[dict] = []

    async def callback(topic: str, payload: dict) -> None:
        received.append(payload)

    token = bus.subscribe("market:quote:SPY", callback)
    await bus.publish("market:quote:SPY", {"price": 1.0})
    await asyncio.sleep(0)
    bus.unsubscribe(token)
    await bus.publish("market:quote:SPY", {"price": 2.0})
    await asyncio.sleep(0)

    assert received == [{"price": 1.0}]


@pytest.mark.asyncio
async def test_bus_unsubscribe_twice_raises() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))

    async def callback(topic: str, payload: dict) -> None:
        pass

    token = bus.subscribe("market:quote:SPY", callback)
    bus.unsubscribe(token)
    with pytest.raises(SubscriberClosedError):
        bus.unsubscribe(token)


@pytest.mark.asyncio
async def test_bus_callback_exception_does_not_break_other_subscribers() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    received: list[dict] = []

    async def good(topic: str, payload: dict) -> None:
        received.append(payload)

    async def bad(topic: str, payload: dict) -> None:
        raise RuntimeError("boom")

    bus.subscribe("market:quote:SPY", bad)
    bus.subscribe("market:quote:SPY", good)
    delivered = await bus.publish("market:quote:SPY", {"price": 1.0})
    await asyncio.sleep(0)

    assert delivered == 2  # both callbacks were dispatched
    assert received == [{"price": 1.0}]
```

Run:

```bash
pytest tests/test_datahub_bus.py -k "bus_publish or bus_register or bus_subscribe or bus_unsubscribe or bus_callback" -x
```

Expected: import error on `core.datahub.Bus`. RED.

- [ ] **Step 2: Implement `Bus` (registration + subscribe/unsubscribe + publish, no TTL/dedupe/throttle yet)**

Create `backend/core/datahub/bus.py`:

```python
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
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from core.datahub.errors import SubscriberClosedError, UnknownTopicError
from core.datahub.matching import pattern_matches
from core.datahub.topic import Topic

logger = logging.getLogger(__name__)


SubscriberCallback = Callable[[str, dict[str, Any]], Awaitable[None]]


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
    """Per-topic mutable state — TTL cache, dedupe key, throttle clock.

    Populated lazily on first publish. Filled out by Task 3.
    """

    topic: Topic
    last_payload: dict[str, Any] | None = None
    last_published_at: float | None = None  # monotonic seconds
    last_payload_at: float | None = None  # monotonic seconds (for TTL)
    last_dedupe_key: Any = field(default=None)


class Bus:
    """In-process topic-based pub/sub.

    Public API:
        register(topic)
        subscribe(pattern, callback) -> SubscriptionToken
        unsubscribe(token)
        publish(topic_name, payload) -> int (count of dispatched callbacks)

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
    # subscribe / unsubscribe
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
        """
        token = SubscriptionToken(token_id=uuid.uuid4().hex)
        self._subscriptions[token.token_id] = _Subscription(
            pattern=pattern, callback=callback, token=token
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

    # ------------------------------------------------------------------
    # publish
    # ------------------------------------------------------------------

    async def publish(self, topic_name: str, payload: dict[str, Any]) -> int:
        """Publish `payload` on `topic_name`.

        Returns the number of subscriber callbacks that were dispatched
        (i.e. matched the topic). A return of 0 with no exception means
        the topic was registered but no live subscribers matched.
        """
        if topic_name not in self._topics:
            raise UnknownTopicError(
                f"topic {topic_name!r} not registered; "
                f"call Bus.register() during service startup"
            )
        # Snapshot subscriptions outside any locked region — callbacks
        # may take a long time and we don't want to hold the lock.
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
```

Update `backend/core/datahub/__init__.py`:

```python
"""DataHub: in-process topic-based pub/sub."""
from __future__ import annotations

from core.datahub.bus import Bus, SubscriberCallback, SubscriptionToken
from core.datahub.errors import (
    BusError,
    SubscriberClosedError,
    UnknownTopicError,
)
from core.datahub.topic import DedupeKeyFn, Topic

__all__ = [
    "Bus",
    "BusError",
    "DedupeKeyFn",
    "SubscriberCallback",
    "SubscriberClosedError",
    "SubscriptionToken",
    "Topic",
    "UnknownTopicError",
]
```

Re-run the new tests:

```bash
pytest tests/test_datahub_bus.py -x
```

Expected: every test from Steps 1+3 of Task 1 plus the six new tests pass. GREEN.

- [ ] **Step 3: Commit**

```bash
git add backend/core/datahub/bus.py backend/core/datahub/__init__.py backend/tests/test_datahub_bus.py
git commit -m "feat(datahub): Bus core — register/subscribe/publish/unsubscribe"
```

---

### Task 3: TTL replay + dedupe + throttle

**Files:**
- Modify: `backend/core/datahub/bus.py`
- Modify: `backend/tests/test_datahub_bus.py`

- [ ] **Step 1: Write failing tests for replay-on-subscribe**

Append to `backend/tests/test_datahub_bus.py`:

```python
# ---------- TTL / replay --------------------------------------------------


@pytest.mark.asyncio
async def test_bus_replay_latest_to_late_subscriber_when_enabled() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY", replay_on_subscribe=True))
    await bus.publish("market:quote:SPY", {"price": 410.0})

    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)
    # Replay is dispatched on subscribe; give the loop one tick.
    await asyncio.sleep(0)

    assert received == [{"price": 410.0}]


@pytest.mark.asyncio
async def test_bus_replay_disabled_when_topic_flag_off() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY", replay_on_subscribe=False))
    await bus.publish("market:quote:SPY", {"price": 1.0})

    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)
    await asyncio.sleep(0)

    assert received == []


@pytest.mark.asyncio
async def test_bus_replay_skipped_when_ttl_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = Bus()
    bus.register(
        Topic(name="market:quote:SPY", replay_on_subscribe=True, ttl_seconds=10.0)
    )
    # Pin the monotonic clock so we can advance it deterministically.
    clock = {"now": 1000.0}
    monkeypatch.setattr("core.datahub.bus._monotonic", lambda: clock["now"])

    await bus.publish("market:quote:SPY", {"price": 1.0})

    # Advance past TTL.
    clock["now"] += 11.0

    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)
    await asyncio.sleep(0)

    assert received == []


# ---------- Dedupe --------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_dedupes_identical_payloads_when_dedupe_fn_set() -> None:
    bus = Bus()
    bus.register(
        Topic(
            name="market:quote:SPY",
            dedupe_key_fn=lambda payload: payload.get("price"),
        )
    )
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)

    delivered_a = await bus.publish("market:quote:SPY", {"price": 1.0, "ts": 1})
    delivered_b = await bus.publish("market:quote:SPY", {"price": 1.0, "ts": 2})
    delivered_c = await bus.publish("market:quote:SPY", {"price": 2.0, "ts": 3})
    await asyncio.sleep(0)

    assert delivered_a == 1
    assert delivered_b == 0  # dropped: same dedupe key as previous publish
    assert delivered_c == 1
    assert received == [{"price": 1.0, "ts": 1}, {"price": 2.0, "ts": 3}]


@pytest.mark.asyncio
async def test_bus_dedupe_disabled_when_no_fn() -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)
    await bus.publish("market:quote:SPY", {"price": 1.0})
    await bus.publish("market:quote:SPY", {"price": 1.0})
    await asyncio.sleep(0)

    assert len(received) == 2


# ---------- Throttle ------------------------------------------------------


@pytest.mark.asyncio
async def test_bus_throttle_drops_publishes_within_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Bus()
    bus.register(Topic(name="signal:SPY:rsi", throttle_seconds=5.0))
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("signal:SPY:rsi", cb)

    clock = {"now": 100.0}
    monkeypatch.setattr("core.datahub.bus._monotonic", lambda: clock["now"])

    delivered_a = await bus.publish("signal:SPY:rsi", {"value": 70})
    clock["now"] += 1.0
    delivered_b = await bus.publish("signal:SPY:rsi", {"value": 71})
    clock["now"] += 5.0
    delivered_c = await bus.publish("signal:SPY:rsi", {"value": 72})
    await asyncio.sleep(0)

    assert delivered_a == 1
    assert delivered_b == 0  # within 5s window
    assert delivered_c == 1
    assert received == [{"value": 70}, {"value": 72}]


@pytest.mark.asyncio
async def test_bus_throttle_zero_means_no_throttle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY", throttle_seconds=0.0))
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    bus.subscribe("market:quote:SPY", cb)
    await bus.publish("market:quote:SPY", {"price": 1.0})
    await bus.publish("market:quote:SPY", {"price": 2.0})
    await asyncio.sleep(0)
    assert len(received) == 2
```

Run:

```bash
pytest tests/test_datahub_bus.py -k "replay or dedupe or throttle" -x
```

Expected: failures (the policies aren't implemented yet, and `_monotonic` is not exported). RED.

- [ ] **Step 2: Implement TTL / replay / dedupe / throttle in `Bus`**

Replace the `_TopicState`, `register`, `subscribe`, and `publish` blocks of `backend/core/datahub/bus.py` with:

```python
"""DataHub bus — in-process topic-based pub/sub.

(... keep the docstring from Task 2 ...)
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
    token_id: str


@dataclass
class _Subscription:
    pattern: str
    callback: SubscriberCallback
    token: SubscriptionToken


@dataclass
class _TopicState:
    topic: Topic
    last_payload: dict[str, Any] | None = None
    last_published_at: float | None = None  # monotonic, for throttle
    last_payload_at: float | None = None  # monotonic, for TTL
    last_dedupe_key: Any = field(default=_SENTINEL)


class Bus:
    """(... unchanged docstring ...)"""

    def __init__(self) -> None:
        self._topics: dict[str, _TopicState] = {}
        self._subscriptions: dict[str, _Subscription] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, topic: Topic) -> None:
        self._topics[topic.name] = _TopicState(topic=topic)

    def topics(self) -> list[Topic]:
        return [state.topic for state in self._topics.values()]

    # ------------------------------------------------------------------
    # subscribe / unsubscribe (with replay)
    # ------------------------------------------------------------------

    def subscribe(
        self,
        pattern: str,
        callback: SubscriberCallback,
    ) -> SubscriptionToken:
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
        if token.token_id not in self._subscriptions:
            raise SubscriberClosedError(f"token {token.token_id!r} unknown")
        del self._subscriptions[token.token_id]

    def subscriber_count(self, topic_name: str) -> int:
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
        except Exception:  # noqa: BLE001
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
```

Re-run:

```bash
pytest tests/test_datahub_bus.py -x
```

Expected: every Task 1/2/3 test passes. GREEN.

- [ ] **Step 2.5: Add slow-consumer / cancellation hardening test**

Append:

```python
# ---------- Hardening -----------------------------------------------------


@pytest.mark.asyncio
async def test_bus_publish_does_not_await_callback_completion() -> None:
    """Publish must return immediately; a hung callback can't block the bus."""
    bus = Bus()
    bus.register(Topic(name="market:quote:SPY"))
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(topic: str, payload: dict) -> None:
        started.set()
        await release.wait()

    bus.subscribe("market:quote:SPY", slow)

    delivered = await asyncio.wait_for(
        bus.publish("market:quote:SPY", {"price": 1.0}),
        timeout=0.5,
    )
    assert delivered == 1

    # Confirm the callback actually started but did not block publish().
    await asyncio.wait_for(started.wait(), timeout=0.5)
    release.set()
```

Run:

```bash
pytest tests/test_datahub_bus.py -x
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/core/datahub/bus.py backend/tests/test_datahub_bus.py
git commit -m "feat(datahub): TTL replay + dedupe + throttle policies on Bus"
```

---

### Task 4: `datahub_service` — process singleton, default topics, lifespan hooks

**Files:**
- Create: `backend/app/services/datahub_service.py`
- Create: `backend/tests/test_datahub_service.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write failing tests for the service singleton + default topic registration**

Create `backend/tests/test_datahub_service.py`:

```python
"""DataHub service-layer tests.

The service module owns the process-singleton Bus and registers the
default topic taxonomy. Tests exercise:

- Singleton: bus() returns the same instance on repeated calls.
- start() registers every default topic.
- start() is idempotent.
- shutdown() drops every subscription and resets the singleton.
- publish() thin wrapper goes through the singleton.
"""
from __future__ import annotations

import asyncio
import pytest

from app.services import datahub_service
from core.datahub import Topic, UnknownTopicError


@pytest.fixture(autouse=True)
async def _reset_singleton() -> None:
    """Each test gets a fresh bus."""
    await datahub_service.shutdown()
    yield
    await datahub_service.shutdown()


@pytest.mark.asyncio
async def test_bus_singleton_is_idempotent() -> None:
    bus_a = datahub_service.bus()
    bus_b = datahub_service.bus()
    assert bus_a is bus_b


@pytest.mark.asyncio
async def test_start_registers_default_topics() -> None:
    await datahub_service.start()
    names = {t.name for t in datahub_service.bus().topics()}

    # Phase 6.1 baseline taxonomy — exact-name examples for each pattern.
    assert "market:quote:_template" in names
    assert "market:trade:_template" in names
    assert "broker:_name:positions" in names
    assert "macro:fred:_code" in names
    assert "signal:_sym:_kind" in names
    assert "agent:verdict:_persona:_sym" in names


@pytest.mark.asyncio
async def test_start_is_idempotent() -> None:
    await datahub_service.start()
    first = datahub_service.bus()
    await datahub_service.start()
    second = datahub_service.bus()
    assert first is second


@pytest.mark.asyncio
async def test_register_topic_adds_to_singleton() -> None:
    await datahub_service.start()
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    names = {t.name for t in datahub_service.bus().topics()}
    assert "market:quote:SPY" in names


@pytest.mark.asyncio
async def test_publish_thin_wrapper() -> None:
    await datahub_service.start()
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append(payload)

    token = datahub_service.bus().subscribe("market:quote:SPY", cb)
    await datahub_service.publish("market:quote:SPY", {"price": 1.0})
    await asyncio.sleep(0)
    datahub_service.bus().unsubscribe(token)

    assert received == [{"price": 1.0}]


@pytest.mark.asyncio
async def test_publish_unknown_topic_raises() -> None:
    await datahub_service.start()
    with pytest.raises(UnknownTopicError):
        await datahub_service.publish("market:quote:DOES_NOT_EXIST", {})


@pytest.mark.asyncio
async def test_shutdown_resets_bus() -> None:
    await datahub_service.start()
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    bus_a = datahub_service.bus()
    await datahub_service.shutdown()
    bus_b = datahub_service.bus()
    assert bus_a is not bus_b
    # Default topics gone too — start() has not been re-called.
    assert datahub_service.bus().topics() == []
```

Run:

```bash
pytest tests/test_datahub_service.py -x
```

Expected: import error on `app.services.datahub_service`. RED.

- [ ] **Step 2: Implement `datahub_service`**

Create `backend/app/services/datahub_service.py`:

```python
"""DataHub service — process singleton + lifespan wiring.

The actual `Bus` lives in `core.datahub`. This module owns:

- The single `Bus` instance for the process.
- Registration of the canonical topic taxonomy at startup.
- Thin `publish()` wrapper so producers don't need to import core directly.
- Lifespan hooks `start()` / `shutdown()` mirrored on `app/scheduler.py`.

We re-create the Bus on every `start()` cycle. There is no persistent
state worth preserving across restarts (subscribers are SSE clients
that reconnect, replay caches are populated within a few seconds of
the first publish).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from core.datahub import Bus, SubscriptionToken, Topic

logger = logging.getLogger(__name__)


# Phase 6.1 canonical taxonomy. The `_template` / `_name` placeholder
# names exist so consumers can inspect the inventory and so glob
# subscriptions like `market:quote:*` work even before any specific
# producer registers a concrete instance like `market:quote:SPY`.
_DEFAULT_TOPICS: tuple[Topic, ...] = (
    Topic(
        name="market:quote:_template",
        ttl_seconds=60.0,
        throttle_seconds=0.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: (p.get("price"), p.get("timestamp")),
    ),
    Topic(
        name="market:trade:_template",
        ttl_seconds=60.0,
        throttle_seconds=0.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: p.get("trade_id"),
    ),
    Topic(
        name="broker:_name:positions",
        ttl_seconds=300.0,
        throttle_seconds=60.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: (p.get("account"), p.get("hash")),
    ),
    Topic(
        name="macro:fred:_code",
        ttl_seconds=86400.0,
        throttle_seconds=60.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: p.get("release_date"),
    ),
    Topic(
        name="signal:_sym:_kind",
        ttl_seconds=900.0,
        throttle_seconds=5.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: (p.get("sym"), p.get("kind"), p.get("value")),
    ),
    Topic(
        name="agent:verdict:_persona:_sym",
        ttl_seconds=3600.0,
        throttle_seconds=5.0,
        replay_on_subscribe=True,
        dedupe_key_fn=lambda p: (p.get("persona"), p.get("sym"), p.get("verdict_id")),
    ),
)


_bus: Bus | None = None
_lock = asyncio.Lock()


def bus() -> Bus:
    """Return the process-wide Bus singleton.

    Lazy: callers that touch the bus before `start()` (e.g. unit tests)
    still get a working empty bus.
    """
    global _bus
    if _bus is None:
        _bus = Bus()
    return _bus


async def start() -> None:
    """Lifespan hook — register every default topic. Idempotent."""
    async with _lock:
        b = bus()
        for topic in _DEFAULT_TOPICS:
            b.register(topic)
        logger.info(
            "datahub_service: registered %d default topics", len(_DEFAULT_TOPICS)
        )


async def shutdown() -> None:
    """Lifespan hook — drop the singleton so the next start() begins clean.

    We do NOT manually unsubscribe each token; SSE clients hold their
    tokens and will hit `SubscriberClosedError` only if they retry
    against the new bus, which is the desired "your stream ended"
    behaviour.
    """
    global _bus
    async with _lock:
        _bus = None


def register_topic(topic: Topic) -> None:
    """Producer-side helper: add a concrete instance topic
    (e.g. `market:quote:SPY`) to the running bus."""
    bus().register(topic)


async def publish(topic_name: str, payload: dict[str, Any]) -> int:
    """Thin wrapper so producers can `from app.services import datahub_service`
    instead of pulling the core package directly."""
    return await bus().publish(topic_name, payload)


def subscribe(
    pattern: str,
    callback,
) -> SubscriptionToken:
    """Symmetrical helper for in-process consumers."""
    return bus().subscribe(pattern, callback)
```

Re-run:

```bash
pytest tests/test_datahub_service.py -x
```

Expected: all 7 tests PASS. GREEN.

- [ ] **Step 3: Wire into `main.py` lifespan**

Open `backend/app/main.py`. In the `from app.services import (...)` block (around line 63), add `datahub_service`:

```python
from app.services import (
    bot_controller,
    datahub_service,
    polygon_ws_publisher,
    scheduled_jobs,
)
```

Inside `lifespan`, BEFORE the `polygon_ws_publisher.start()` call, add:

```python
    await datahub_service.start()
```

In the `finally:` block, BEFORE `await app_scheduler.shutdown()` and AFTER `await polygon_ws_publisher.shutdown()`, add:

```python
        await datahub_service.shutdown()
```

So the relevant region of `lifespan` becomes:

```python
    await init_database()
    await app_scheduler.start()
    scheduled_jobs.register_default_jobs()

    # ... existing workflow_jobs registration ...

    await datahub_service.start()
    await polygon_ws_publisher.start()

    # ... existing user-strategy reload ...

    try:
        yield
    finally:
        await polygon_ws_publisher.shutdown()
        await datahub_service.shutdown()
        await app_scheduler.shutdown()
        await bot_controller.shutdown_bot()
```

Run the smoke test to confirm lifespan still imports:

```bash
pytest tests/test_app_smoke.py -x
```

Expected: existing 6 pre-existing failures unchanged; no new failures from the lifespan change.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/datahub_service.py backend/tests/test_datahub_service.py backend/app/main.py
git commit -m "feat(datahub): service singleton + lifespan wiring + default topic taxonomy"
```

---

### Task 5: SSE bridge router `/api/datahub/...`

**Files:**
- Create: `backend/app/routers/datahub.py`
- Create: `backend/app/models/datahub.py`
- Create: `backend/tests/test_datahub_router.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Write failing tests for `/api/datahub/topics` and `/api/datahub/latest`**

Create `backend/tests/test_datahub_router.py`:

```python
"""DataHub router tests."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import datahub_service
from core.datahub import Topic


@pytest.fixture(autouse=True)
async def _reset_singleton() -> None:
    await datahub_service.shutdown()
    await datahub_service.start()
    yield
    await datahub_service.shutdown()


def test_topics_inventory_lists_default_taxonomy() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/datahub/topics")
    assert resp.status_code == 200
    body = resp.json()
    assert "topics" in body
    names = {t["name"] for t in body["topics"]}
    assert "market:quote:_template" in names
    assert "broker:_name:positions" in names
    sample = next(t for t in body["topics"] if t["name"] == "market:quote:_template")
    assert sample["ttl_seconds"] == 60.0
    assert sample["replay_on_subscribe"] is True


@pytest.mark.asyncio
async def test_latest_returns_404_when_no_publish() -> None:
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    with TestClient(app) as client:
        resp = client.get("/api/datahub/latest/market:quote:SPY")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_latest_returns_cached_payload_after_publish() -> None:
    datahub_service.register_topic(
        Topic(name="market:quote:SPY", ttl_seconds=60.0, replay_on_subscribe=True)
    )
    await datahub_service.publish("market:quote:SPY", {"price": 410.0})
    with TestClient(app) as client:
        resp = client.get("/api/datahub/latest/market:quote:SPY")
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] == "market:quote:SPY"
    assert body["payload"] == {"price": 410.0}


def test_latest_returns_404_for_unknown_topic() -> None:
    with TestClient(app) as client:
        resp = client.get("/api/datahub/latest/market:quote:NOPE")
    assert resp.status_code == 404
```

Run:

```bash
pytest tests/test_datahub_router.py -x
```

Expected: 404 from FastAPI on `/api/datahub/topics` (route missing). RED.

- [ ] **Step 2: Implement Pydantic models**

Create `backend/app/models/datahub.py`:

```python
"""DataHub HTTP response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicListItem(BaseModel):
    name: str
    ttl_seconds: float | None = None
    throttle_seconds: float = 0.0
    replay_on_subscribe: bool = False
    has_dedupe_fn: bool = False


class TopicListResponse(BaseModel):
    topics: list[TopicListItem] = Field(default_factory=list)


class LatestEventResponse(BaseModel):
    topic: str
    payload: dict[str, Any]
```

- [ ] **Step 3: Implement the router**

Create `backend/app/routers/datahub.py`:

```python
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
```

- [ ] **Step 4: Mount the router in `main.py`**

Open `backend/app/main.py`. Locate the block of `from app.routers import ...` lines and add:

```python
from app.routers import datahub as datahub_router
```

Locate the `app.include_router(...)` block (search for `include_router` if needed) and append:

```python
app.include_router(datahub_router.router)
```

- [ ] **Step 5: Re-run the router tests**

```bash
pytest tests/test_datahub_router.py -x
```

Expected: 4 PASS. GREEN.

- [ ] **Step 6: SSE bridge end-to-end test**

Append to `backend/tests/test_datahub_router.py`:

```python
@pytest.mark.asyncio
async def test_sse_stream_delivers_published_events() -> None:
    """End-to-end: publish on the bus, consume via the SSE endpoint."""
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    chunks: list[bytes] = []

    with TestClient(app) as client:
        with client.stream(
            "GET", "/api/datahub/stream/market:quote:*"
        ) as resp:
            # Read the first ":connected" comment so the route handler has
            # subscribed to the bus.
            for raw in resp.iter_raw():
                chunks.append(raw)
                if b"connected" in raw:
                    break

            # Publish — the callback will push into the queue from the
            # background task. Poll iter_raw() in a loop with a deadline.
            await datahub_service.publish(
                "market:quote:SPY", {"price": 410.0}
            )

            deadline = asyncio.get_event_loop().time() + 3.0
            payload_seen = False
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = next(resp.iter_raw())
                except StopIteration:
                    break
                chunks.append(chunk)
                if b"\"price\": 410.0" in chunk:
                    payload_seen = True
                    break
            assert payload_seen, b"".join(chunks)
```

Run:

```bash
pytest tests/test_datahub_router.py -x
```

Expected: 5 PASS. GREEN.

> Note on TestClient streaming behaviour: `iter_raw()` blocks on the
> server task; in some environments `next()` over the iterator hangs
> until the next byte arrives. If this test is flaky in CI, fall back
> to using httpx.AsyncClient with `stream("GET", ...)` and `aiter_raw()`
> driven by `asyncio.wait_for`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/datahub.py backend/app/models/datahub.py backend/tests/test_datahub_router.py backend/app/main.py
git commit -m "feat(datahub): SSE bridge router /api/datahub/{topics,latest,stream}"
```

---

### Task 6: Migrate Polygon WS publisher onto the bus

**Files:**
- Modify: `backend/app/services/polygon_ws_publisher.py`
- Create / Append: `backend/tests/test_datahub_service.py` (new test class)

- [ ] **Step 1: Write failing test for the migrated publisher**

Append to `backend/tests/test_datahub_service.py`:

```python
# ---------- Polygon WS migration ------------------------------------------


@pytest.mark.asyncio
async def test_polygon_ws_publisher_emits_via_datahub() -> None:
    """`_publish_tick` must register the per-symbol topic on demand and
    publish the payload through datahub_service."""
    from app.services import polygon_ws_publisher

    await datahub_service.start()
    received: list[dict] = []

    async def cb(topic: str, payload: dict) -> None:
        received.append({"topic": topic, "payload": payload})

    datahub_service.bus().subscribe("market:quote:*", cb)

    payload = {"symbol": "SPY", "price": 410.5, "timestamp": 1714000000}
    await polygon_ws_publisher._publish_tick(payload)
    await asyncio.sleep(0)

    assert received == [
        {"topic": "market:quote:SPY", "payload": payload}
    ]
```

Run:

```bash
pytest tests/test_datahub_service.py::test_polygon_ws_publisher_emits_via_datahub -x
```

Expected: failure — current `_publish_tick` posts to `event_bus.publish("quote:{sym}", ...)`, not the new bus. RED.

- [ ] **Step 2: Migrate `_publish_tick`**

Open `backend/app/services/polygon_ws_publisher.py`. Replace the `_publish_tick` function and its imports.

Replace:

```python
from app.streaming import event_bus
```

with:

```python
from app.services import datahub_service
from core.datahub import Topic, UnknownTopicError
```

Replace the entire body of `_publish_tick`:

```python
async def _publish_tick(payload: dict[str, Any]) -> None:
    """Forward one tick payload onto the DataHub bus.

    Polygon ticks come in normalized to at least
    ``{"symbol", "price", "timestamp"}``. We translate to topic
    ``market:quote:{SYMBOL}`` (uppercased) and lazily register the
    concrete topic the first time we see a symbol — this keeps the
    default taxonomy small while still letting `register_topic` apply
    the canonical TTL/dedupe/throttle policy from the template.
    """
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        return
    topic_name = f"market:quote:{symbol}"
    bus = datahub_service.bus()
    # Register on first sight; idempotent.
    if topic_name not in {t.name for t in bus.topics()}:
        datahub_service.register_topic(
            Topic(
                name=topic_name,
                ttl_seconds=60.0,
                throttle_seconds=0.0,
                replay_on_subscribe=True,
                dedupe_key_fn=lambda p: (p.get("price"), p.get("timestamp")),
            )
        )
    try:
        await datahub_service.publish(topic_name, payload)
    except UnknownTopicError:  # extremely unlikely (race with shutdown)
        logger.debug("polygon_ws_publisher: bus shut down mid-publish")
    except Exception:  # noqa: BLE001 — bus errors must not kill the WS loop
        logger.exception("polygon_ws_publisher: bus publish failed")
```

Re-run:

```bash
pytest tests/test_datahub_service.py -x
```

Expected: PASS, including the new migration test.

- [ ] **Step 3: Confirm no other call sites of `event_bus.publish("quote:...")` remain**

```bash
grep -rn "event_bus.publish" /Users/yugu/NewBirdClaude/backend/app/
grep -rn "quote:{" /Users/yugu/NewBirdClaude/backend/app/
```

Expected: only matches inside `streaming.py` (the legacy module itself, which we'll keep as a shim in Task 7) and any tests for that module. No other producer should still hit the old topic name.

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/polygon_ws_publisher.py backend/tests/test_datahub_service.py
git commit -m "refactor(polygon-ws): publish ticks via datahub bus on market:quote:{sym}"
```

---

### Task 7: Migrate the legacy SSE consumer (`routers/stream.py` + `streaming.py` shim)

**Goal:** keep the old URL surface (`GET /api/stream/{topic:path}`, `GET /api/stream/{topic:path}/latest`) working while the bytes flow through the new bus. We do this by translating the legacy topic name (`quote:SPY`) to the new name (`market:quote:SPY`) and subscribing through `datahub_service`.

**Files:**
- Modify: `backend/app/routers/stream.py`
- Modify: `backend/app/streaming.py`
- Modify: `backend/tests/test_datahub_router.py` (add legacy-compat test)

- [ ] **Step 1: Write failing test for legacy URL forwarding**

Append to `backend/tests/test_datahub_router.py`:

```python
@pytest.mark.asyncio
async def test_legacy_stream_url_still_works() -> None:
    """`GET /api/stream/quote:SPY` should keep delivering `market:quote:SPY`
    publishes for a transition window."""
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    chunks: list[bytes] = []

    with TestClient(app) as client:
        with client.stream("GET", "/api/stream/quote:SPY") as resp:
            for raw in resp.iter_raw():
                chunks.append(raw)
                if b"connected" in raw:
                    break
            await datahub_service.publish("market:quote:SPY", {"price": 1.0})
            deadline = asyncio.get_event_loop().time() + 3.0
            payload_seen = False
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = next(resp.iter_raw())
                except StopIteration:
                    break
                chunks.append(chunk)
                if b"\"price\": 1.0" in chunk:
                    payload_seen = True
                    break
            assert payload_seen
```

Run:

```bash
pytest tests/test_datahub_router.py::test_legacy_stream_url_still_works -x
```

Expected: failure — the legacy router currently subscribes to the old `event_bus`, which is now disconnected from real producers. RED.

- [ ] **Step 2: Rewrite `routers/stream.py` as a thin forwarder**

Replace the entire body of `backend/app/routers/stream.py` with:

```python
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
```

- [ ] **Step 3: Reduce `streaming.py` to a thin shim**

Replace the body of `backend/app/streaming.py` with:

```python
"""DEPRECATED — single-topic EventBus shim.

Kept only so any in-process import of ``from app.streaming import event_bus``
still resolves. New code uses ``app.services.datahub_service``.

Removal target: Phase 6.2.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services import datahub_service
from core.datahub import Topic, UnknownTopicError

logger = logging.getLogger(__name__)


class _LegacyEventBusShim:
    """Translates legacy short topic names (`quote:SPY`) into canonical
    DataHub names (`market:quote:SPY`)."""

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


event_bus = _LegacyEventBusShim()
```

Run all three test files:

```bash
pytest tests/test_datahub_bus.py tests/test_datahub_service.py tests/test_datahub_router.py -x
```

Expected: every test passes including the new `test_legacy_stream_url_still_works`. GREEN.

- [ ] **Step 4: Confirm pre-existing streaming tests still pass**

```bash
pytest tests/ -k "stream and not datahub" -x
```

Expected: pre-existing tests continue to pass (the shim preserves the import surface).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/stream.py backend/app/streaming.py backend/tests/test_datahub_router.py
git commit -m "refactor(stream): legacy /api/stream forwards via datahub bus shim"
```

---

### Task 8: OpenAPI parity entries

**Files:**
- Modify: `backend/tests/test_openapi_parity.py`

- [ ] **Step 1: Read the parity test to find the exact insertion point**

```bash
grep -n "/api/stream" /Users/yugu/NewBirdClaude/backend/tests/test_openapi_parity.py
```

Expected: the existing entries on lines 136–137:

```python
("GET",    "/api/stream/{topic:path}"),
("GET",    "/api/stream/{topic:path}/latest"),
```

- [ ] **Step 2: Add new DataHub entries**

Edit `backend/tests/test_openapi_parity.py`. Immediately after the two `/api/stream/...` tuples, add:

```python
    ("GET",    "/api/datahub/topics"),
    ("GET",    "/api/datahub/latest/{topic:path}"),
    ("GET",    "/api/datahub/stream/{topic_pattern:path}"),
```

- [ ] **Step 3: Run the parity test**

```bash
pytest tests/test_openapi_parity.py -x
```

Expected: PASS. If the test fails because the parameter name in the OpenAPI schema is slightly different (e.g. FastAPI reports `topic` instead of `topic_pattern`), adjust the tuple to match the actual schema; the FastAPI behaviour is the source of truth.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_openapi_parity.py
git commit -m "test(openapi): add parity entries for /api/datahub routes"
```

---

### Task 9: Smoke test (curl + EventSource consumer) and final verification

This task has no production code — it is the integration test that confirms a real curl + a real Python EventSource-style consumer work against a live `uvicorn` process. It also runs the whole test suite one last time.

**Files:**
- (no source modifications)
- This task uses one ad-hoc Python script in `/tmp` for the EventSource consumer; it is NOT committed.

- [ ] **Step 1: Boot the server**

In one terminal, from `backend/`:

```bash
uvicorn app.main:app --reload --port 8001
```

Wait for `Application startup complete`.

- [ ] **Step 2: Inventory check via curl**

In another terminal:

```bash
curl -s http://localhost:8001/api/datahub/topics | python3 -m json.tool
```

Expected: a JSON object with a `topics` array containing at least the six default topics
(`market:quote:_template`, `market:trade:_template`, `broker:_name:positions`,
`macro:fred:_code`, `signal:_sym:_kind`, `agent:verdict:_persona:_sym`).

- [ ] **Step 3: 404 on missing snapshot**

```bash
curl -i http://localhost:8001/api/datahub/latest/market:quote:NOPE
```

Expected: `HTTP/1.1 404 Not Found`.

- [ ] **Step 4: SSE stream + manual publish round-trip**

Create `/tmp/datahub_consumer.py`:

```python
"""Smoke EventSource-style consumer.

Reads /api/datahub/stream/market:quote:* and prints every event for 30s.
"""
from __future__ import annotations

import asyncio
import sys

import httpx


async def main() -> None:
    timeout = httpx.Timeout(connect=5.0, read=None, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "GET",
            "http://localhost:8001/api/datahub/stream/market:quote:*",
        ) as resp:
            print(f"status={resp.status_code}", file=sys.stderr)
            async for line in resp.aiter_lines():
                if line:
                    print(line, flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
```

Run from `backend/` with the venv active:

```bash
python3 /tmp/datahub_consumer.py &
```

Now publish from a Python REPL (still with the venv active, in a fresh terminal):

```bash
python3 - <<'PY'
import asyncio
from app.services import datahub_service
from core.datahub import Topic

async def go():
    await datahub_service.start()
    datahub_service.register_topic(Topic(name="market:quote:SPY"))
    n = await datahub_service.publish("market:quote:SPY", {"price": 410.5, "timestamp": 1714000000})
    print(f"delivered={n}")

asyncio.run(go())
PY
```

> Note: this REPL spawns its OWN datahub singleton in the calling Python
> process, NOT in the uvicorn process. To publish into the running
> uvicorn server we instead trigger a publish via the running
> `polygon_ws_publisher` (Step 5), or temporarily expose a debug-only
> route. For Step 4 the goal is to confirm the consumer connects and
> receives the `:connected` and `:keepalive` framing — not necessarily
> to see a real publish round-trip in this exact step.

Expected output in the consumer terminal:

```
status=200
: connected
: keepalive
: keepalive
...
```

Kill the consumer (`fg`, Ctrl-C).

- [ ] **Step 5: Real producer round-trip via Polygon stub**

Stop the uvicorn process (Ctrl-C) and start it with the Polygon WebSocket DISABLED but with a one-shot producer hooked up via a debug route.

Create a temporary debug script `/tmp/datahub_producer.py`:

```python
"""Smoke producer — drives a real publish into the running server.

Approach: hit a debug HTTP route that internally calls
datahub_service.publish. Phase 6.1 does NOT add such a route to the
production codebase; for the smoke test we use the SSE bridge in a
two-process setup by piggy-backing on the legacy `event_bus.publish`
shim through a fresh import in the SAME process.

Practical alternative: enable the Polygon WS publisher with a real
POLYGON_API_KEY in `runtime_settings`, restart uvicorn, and watch
ticks flow into the consumer. Document outcome here.
"""
```

The real validation of an in-process round-trip happens in
`tests/test_datahub_router.py::test_sse_stream_delivers_published_events`
(Task 5 Step 6), which uses `TestClient` and runs publish in the same
process as the SSE handler. The Step 5 box here is OPTIONAL —
check it off if you have valid Polygon credentials and want to see a
real-world round-trip; otherwise rely on the unit + integration tests.

- [ ] **Step 6: Run the entire datahub test suite**

```bash
cd backend
pytest tests/test_datahub_bus.py tests/test_datahub_service.py tests/test_datahub_router.py tests/test_openapi_parity.py -x
```

Expected: ALL PASS.

- [ ] **Step 7: Run the entire backend test suite under `unittest discover`**

CI runs stdlib unittest, not pytest. Confirm compatibility:

```bash
cd backend
python -m unittest discover -s tests
```

Expected: same pre-existing 6 failures as before this plan; no new failures introduced by the DataHub work.

- [ ] **Step 8: Lint**

```bash
ruff check backend/core/datahub backend/app/services/datahub_service.py backend/app/routers/datahub.py backend/app/models/datahub.py
```

Expected: no errors. Fix any reported issue and re-run.

- [ ] **Step 9: Final commit + push**

```bash
git status
git log --oneline feat/datahub-mcp..HEAD  # or main..HEAD if branched from main
```

If anything is unstaged, decide whether it belongs in a follow-up plan. Then push:

```bash
git push -u origin feat/datahub-mcp
```

(Branch name comes from the master roadmap Phase 6 spec.)

---

## Self-Review Checklist

Before merging, verify each item:

- [ ] `backend/core/datahub/` is pure — no FastAPI imports, no `app.*` imports, importable from the REPL with just stdlib.
- [ ] `Topic` is a `@dataclass(frozen=True)` (immutability).
- [ ] `Bus.publish` raises `UnknownTopicError` on unregistered topics — silent drops are NOT acceptable.
- [ ] `Bus._safe_invoke` swallows non-cancellation exceptions and logs them; one bad subscriber does not poison others.
- [ ] `Bus.publish` returns immediately and never awaits subscriber callbacks (covered by `test_bus_publish_does_not_await_callback_completion`).
- [ ] Glob matching: `market:quote:*` matches `market:quote:SPY`, exact strings short-circuit before fnmatch (covered by `test_pattern_matches`).
- [ ] TTL: replay caches respect `ttl_seconds`; expired caches don't replay (covered by `test_bus_replay_skipped_when_ttl_expired`).
- [ ] Dedupe: identical key drops the second publish (covered by `test_bus_dedupes_identical_payloads_when_dedupe_fn_set`).
- [ ] Throttle: publishes inside the throttle window are dropped (covered by `test_bus_throttle_drops_publishes_within_window`).
- [ ] `datahub_service.start()` registers all six default topics (covered by `test_start_registers_default_topics`).
- [ ] `datahub_service.shutdown()` resets the singleton (covered by `test_shutdown_resets_bus`).
- [ ] Polygon WS publisher uses `datahub_service.publish("market:quote:{SYM}", ...)` and lazy-registers the per-symbol topic.
- [ ] Legacy `/api/stream/quote:SPY` URL still streams (covered by `test_legacy_stream_url_still_works`).
- [ ] `app.streaming.event_bus.publish("quote:SPY", ...)` shim still works for any pre-migration import.
- [ ] OpenAPI parity test includes the three new `/api/datahub/...` routes.
- [ ] No `os.environ` reads added — keys still flow through `runtime_settings`.
- [ ] No new third-party dependency added. `requirements.txt` is unchanged.
- [ ] `main.py` lifespan ordering: `datahub_service.start()` BEFORE `polygon_ws_publisher.start()`; `datahub_service.shutdown()` AFTER `polygon_ws_publisher.shutdown()`.
- [ ] All files <800 LOC, all functions <50 LOC.
- [ ] Module/class/method docstrings present and explain "why", not just "what".
- [ ] `python -m unittest discover -s tests` produces no NEW failures.

---

## Follow-Ups (Out of Scope for Phase 6.1)

The following are deliberately deferred. Each is a separate follow-up plan.

1. **Phase 6.1.1 — Migrate `social_signal` producer onto `signal:{sym}:{kind}`.** The signal pipeline currently writes to its own DB-backed table; once the bus is in place, every classification result should also be `publish`ed for live UI consumption.
2. **Phase 6.1.2 — Migrate `position_sync_service` onto `broker:{name}:positions`.** Hook the existing 5-min IBKR snapshot job to publish the snapshot payload after it persists to the DB.
3. **Phase 6.1.3 — Migrate `macro_service` onto `macro:fred:{code}`.** Daily 14:00 UTC FRED refresh fans out per-series.
4. **Phase 6.2 — Frontend migration.** Switch `frontend-v2/src/lib/sse.js` from `/api/stream/{topic}` to `/api/datahub/stream/{topic_pattern}`. Once every consumer is migrated, delete `routers/stream.py` and `app/streaming.py` shim.
5. **Phase 6.3 — MCP tool exposure.** Wrap `datahub_service.bus().latest(topic)` and `datahub_service.bus().topics()` as MCP tools so the AI Council can read live state during chat.
6. **Phase 6.x — Multi-process / Redis backend.** Replace the in-process `Bus` internals with a Redis pub/sub-backed implementation behind the same interface. No caller code changes.
7. **Bus metrics endpoint.** `GET /api/datahub/metrics` exposing per-topic publish-count, drop-count (dedupe), drop-count (throttle), subscriber-count. Useful once we have observability dashboards.
8. **Bounded queue per SSE subscriber.** The current SSE bridge uses an unbounded `asyncio.Queue`; under a slow client this could pile up. Add `maxsize=100` with the same drop-oldest policy as the legacy `EventBus`.
9. **Topic ACLs.** Some topics (e.g. `broker:*:positions`) leak portfolio data; the SSE endpoint should require the same auth gate as `/api/portfolio/...`. Out of scope here because no SSE auth model exists yet.
10. **Per-subscriber pattern restrictions.** Today any client can subscribe to `*` and see every topic; once auth lands we should restrict broad globs to admin tokens.
