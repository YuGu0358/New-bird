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
