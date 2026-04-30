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
