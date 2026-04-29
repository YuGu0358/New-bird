"""Tests for app.streaming - EventBus + SSE endpoint."""
from __future__ import annotations

import asyncio

import pytest

from app.streaming import Event, EventBus, event_bus


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    """Each test starts with no subscribers."""
    event_bus.reset()
    yield
    event_bus.reset()


# ---------- EventBus core ----------


@pytest.mark.asyncio
async def test_publish_with_no_subscribers_returns_zero() -> None:
    bus = EventBus()
    delivered = await bus.publish("nobody-listening", {"x": 1})
    assert delivered == 0


@pytest.mark.asyncio
async def test_subscribe_receives_published_event() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def consumer() -> None:
        async for event in bus.subscribe("test:topic"):
            received.append(event)
            if len(received) >= 1:
                break

    task = asyncio.create_task(consumer())
    # Yield once so the consumer registers its queue before we publish.
    await asyncio.sleep(0)
    delivered = await bus.publish("test:topic", {"hello": "world"})
    await asyncio.wait_for(task, timeout=1.0)

    assert delivered == 1
    assert len(received) == 1
    assert received[0].topic == "test:topic"
    assert received[0].data == {"hello": "world"}


@pytest.mark.asyncio
async def test_subscribers_get_independent_streams() -> None:
    bus = EventBus()
    a_received: list[Event] = []
    b_received: list[Event] = []

    async def consumer_a() -> None:
        async for event in bus.subscribe("multi"):
            a_received.append(event)
            if len(a_received) >= 1:
                break

    async def consumer_b() -> None:
        async for event in bus.subscribe("multi"):
            b_received.append(event)
            if len(b_received) >= 1:
                break

    task_a = asyncio.create_task(consumer_a())
    task_b = asyncio.create_task(consumer_b())
    await asyncio.sleep(0)
    delivered = await bus.publish("multi", {"n": 42})
    await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=1.0)

    assert delivered == 2
    assert a_received[0].data == {"n": 42}
    assert b_received[0].data == {"n": 42}


@pytest.mark.asyncio
async def test_subscriber_unregistered_after_aclose() -> None:
    """Async generator finally clauses run on `aclose()` — verify cleanup
    happens when the consumer explicitly closes the iterator (which is
    what the SSE endpoint does in its try/finally)."""
    bus = EventBus()

    agen = bus.subscribe("once")
    # Pull the agen to register the queue. Use anext to start it.
    consumer_task = asyncio.create_task(agen.__anext__())
    await asyncio.sleep(0)  # let the generator register
    assert bus.subscriber_count("once") == 1

    await bus.publish("once", {"x": 1})
    await consumer_task  # delivered the event

    # Now close the generator — its finally block must remove the queue.
    await agen.aclose()
    assert bus.subscriber_count("once") == 0


@pytest.mark.asyncio
async def test_topic_isolation() -> None:
    """A publish on topic A shouldn't reach a subscriber on topic B."""
    bus = EventBus()
    received: list[Event] = []

    async def consumer() -> None:
        try:
            async for event in bus.subscribe("topic-a"):
                received.append(event)
        except asyncio.CancelledError:
            raise

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    delivered = await bus.publish("topic-b", {"unrelated": True})
    # Give the consumer a tick to receive (it shouldn't).
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert delivered == 0  # no subscribers on topic-b
    assert received == []


def test_event_to_sse_format_terminates_with_blank_line() -> None:
    event = Event(topic="t", data={"k": "v"})
    wire = event.to_sse()
    assert wire.startswith("event: t\n")
    assert "data: " in wire
    assert wire.endswith("\n\n")


def test_event_subscriber_count_helper() -> None:
    bus = EventBus()
    assert bus.subscriber_count("none") == 0


# ---------- Endpoint sanity ----------
# Full SSE-over-TestClient is awkward to test deterministically (the
# generator blocks on queue.get() with a 15s keepalive timeout, so
# `next(iter_text())` would have to wait that long). Instead we verify
# the route is registered with the right shape; the wire format is
# already covered by `test_event_to_sse_format_terminates_with_blank_line`
# and end-to-end the wave's curl smoke covers the live endpoint.


def test_stream_route_is_registered() -> None:
    from app.main import app

    paths = {
        getattr(route, "path", "")
        for route in app.routes
        if hasattr(route, "methods")
    }
    assert "/api/stream/{topic:path}" in paths


from datetime import timedelta


# ---------- Last-value cache ----------


@pytest.mark.asyncio
async def test_latest_returns_none_when_topic_never_published() -> None:
    bus = EventBus()
    assert bus.latest("never") is None


@pytest.mark.asyncio
async def test_latest_returns_most_recent_event() -> None:
    bus = EventBus()
    await bus.publish("topic", {"v": 1})
    await bus.publish("topic", {"v": 2})
    snapshot = bus.latest("topic")
    assert snapshot is not None
    assert snapshot.data == {"v": 2}


@pytest.mark.asyncio
async def test_latest_isolated_per_topic() -> None:
    bus = EventBus()
    await bus.publish("a", {"v": "alpha"})
    await bus.publish("b", {"v": "bravo"})
    assert bus.latest("a").data == {"v": "alpha"}
    assert bus.latest("b").data == {"v": "bravo"}


@pytest.mark.asyncio
async def test_publish_with_ttl_expires_cache() -> None:
    """A 1ms TTL should immediately make latest() return None."""
    bus = EventBus()
    await bus.publish("topic", {"v": 1}, ttl=timedelta(milliseconds=1))
    # Sleep slightly longer than the TTL.
    await asyncio.sleep(0.01)
    assert bus.latest("topic") is None


@pytest.mark.asyncio
async def test_publish_without_ttl_persists() -> None:
    bus = EventBus()
    await bus.publish("topic", {"v": 1})
    await asyncio.sleep(0.05)
    assert bus.latest("topic") is not None


# ---------- replay_latest ----------


@pytest.mark.asyncio
async def test_subscribe_replay_latest_yields_cached_first() -> None:
    bus = EventBus()
    await bus.publish("topic", {"v": "snapshot"})

    received: list[Event] = []
    agen = bus.subscribe("topic", replay_latest=True)

    # Pull the first event — should be the cached snapshot.
    first = await agen.__anext__()
    received.append(first)

    # Now publish a live event; should arrive next.
    await bus.publish("topic", {"v": "live"})
    second = await asyncio.wait_for(agen.__anext__(), timeout=1.0)
    received.append(second)

    await agen.aclose()

    assert len(received) == 2
    assert received[0].data == {"v": "snapshot"}
    assert received[1].data == {"v": "live"}


@pytest.mark.asyncio
async def test_subscribe_replay_latest_skipped_when_no_cache() -> None:
    bus = EventBus()
    received: list[Event] = []

    async def consumer() -> None:
        async for event in bus.subscribe("topic", replay_latest=True):
            received.append(event)
            break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await bus.publish("topic", {"v": "first"})
    await asyncio.wait_for(task, timeout=1.0)
    # No cache existed → only the live event arrives.
    assert len(received) == 1
    assert received[0].data == {"v": "first"}


@pytest.mark.asyncio
async def test_subscribe_replay_latest_default_off() -> None:
    """Without `replay_latest=True`, cached values are NOT yielded."""
    bus = EventBus()
    await bus.publish("topic", {"v": "old"})

    received: list[Event] = []

    async def consumer() -> None:
        async for event in bus.subscribe("topic"):  # default kwarg
            received.append(event)
            break

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await bus.publish("topic", {"v": "new"})
    await asyncio.wait_for(task, timeout=1.0)
    assert received[0].data == {"v": "new"}


# ---------- reset() must clear cache ----------


@pytest.mark.asyncio
async def test_reset_clears_cache() -> None:
    bus = EventBus()
    await bus.publish("topic", {"v": 1})
    assert bus.latest("topic") is not None
    bus.reset()
    assert bus.latest("topic") is None


# ---------- /api/stream/{topic}/latest endpoint ----------


def test_latest_endpoint_returns_404_when_no_cache() -> None:
    """Bare TestClient — endpoint should 404 with a clean detail when no
    event has been published to the topic yet."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/stream/never-published/latest")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_latest_endpoint_returns_cached_event() -> None:
    """Publish first, then GET — endpoint should return the cached event JSON."""
    from fastapi.testclient import TestClient
    from app.main import app

    await event_bus.publish("test:cache", {"price": 42.0})

    client = TestClient(app)
    resp = client.get("/api/stream/test:cache/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] == "test:cache"
    assert body["data"] == {"price": 42.0}
    assert "occurred_at" in body
