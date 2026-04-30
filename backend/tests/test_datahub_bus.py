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
