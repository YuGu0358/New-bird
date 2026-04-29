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
