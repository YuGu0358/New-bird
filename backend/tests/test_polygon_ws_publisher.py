"""Tests for the Polygon WebSocket → EventBus publisher.

The actual `_run_sdk_stream` is mocked end-to-end; we exercise:
- disabled flag → no-op start (no task created)
- missing API key → no-op start
- enabled + key + mocked stream → publishes ticks to event_bus
- transient stream error → backoff + reconnect
- shutdown cancels the inner task

We patch the publisher's settings helpers directly rather than relying on
``monkeypatch.setenv`` — ``runtime_settings.get_setting`` reads the SQLite
``app_settings`` table BEFORE consulting environment variables, so a
locally-stored API key would otherwise leak into tests.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services import polygon_ws_publisher
from app.streaming import Event, event_bus


def _enable(monkeypatch: pytest.MonkeyPatch, *, enabled: bool, key: bool) -> None:
    """Force the publisher's gating helpers to known values."""
    monkeypatch.setattr(polygon_ws_publisher, "_is_enabled", lambda: enabled)
    monkeypatch.setattr(
        polygon_ws_publisher, "_api_key_configured", lambda: key
    )
    # Lock the watchlist down so tests don't depend on env / DB state.
    monkeypatch.setattr(
        polygon_ws_publisher, "_watchlist", lambda: ["SPY", "QQQ"]
    )


@pytest.fixture(autouse=True)
async def _reset_state() -> None:
    """Each test starts with no task + clean bus."""
    polygon_ws_publisher._reset_for_tests()  # noqa: SLF001
    event_bus.reset()
    yield
    await polygon_ws_publisher.shutdown()
    polygon_ws_publisher._reset_for_tests()  # noqa: SLF001
    event_bus.reset()


@pytest.mark.asyncio
async def test_start_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, enabled=False, key=True)
    await polygon_ws_publisher.start()
    assert not polygon_ws_publisher.is_running()


@pytest.mark.asyncio
async def test_start_noop_when_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, enabled=True, key=False)
    await polygon_ws_publisher.start()
    assert not polygon_ws_publisher.is_running()


@pytest.mark.asyncio
async def test_start_runs_when_enabled_and_publishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock _run_sdk_stream so it calls our handler with a tick then waits."""
    _enable(monkeypatch, enabled=True, key=True)

    received: list[Event] = []

    async def fake_stream(symbols, on_tick):
        # Simulate one tick then keep the connection alive forever.
        await on_tick({"symbol": "SPY", "price": 500.0, "timestamp": "now"})
        await on_tick({"symbol": "QQQ", "price": 400.0, "timestamp": "now"})
        await asyncio.Event().wait()  # block until cancelled

    monkeypatch.setattr(
        polygon_ws_publisher.polygon_service,
        "_run_sdk_stream",
        fake_stream,
    )

    received_evt = asyncio.Event()

    async def consume() -> None:
        async for evt in event_bus.subscribe("quote:SPY"):
            received.append(evt)
            received_evt.set()
            break

    consumer_task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let the consumer register

    await polygon_ws_publisher.start()
    assert polygon_ws_publisher.is_running()

    await asyncio.wait_for(received_evt.wait(), timeout=2.0)
    await consumer_task
    assert len(received) == 1
    assert received[0].topic == "quote:SPY"
    assert received[0].data["symbol"] == "SPY"
    assert received[0].data["price"] == 500.0


@pytest.mark.asyncio
async def test_stream_error_triggers_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """First call raises; second call publishes one tick. Expect publisher to retry."""
    _enable(monkeypatch, enabled=True, key=True)

    # Override the backoff schedule to be fast for tests.
    monkeypatch.setattr(
        polygon_ws_publisher,
        "_BACKOFF_SCHEDULE_SECONDS",
        (0,),  # zero-second backoff so the test is fast
    )

    call_count = {"n": 0}

    async def fake_stream(symbols, on_tick):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated WS drop")
        await on_tick({"symbol": "SPY", "price": 500.0, "timestamp": "now"})
        await asyncio.Event().wait()

    monkeypatch.setattr(
        polygon_ws_publisher.polygon_service,
        "_run_sdk_stream",
        fake_stream,
    )

    received_evt = asyncio.Event()

    async def consume() -> None:
        async for _ in event_bus.subscribe("quote:SPY"):
            received_evt.set()
            break

    consumer_task = asyncio.create_task(consume())
    await asyncio.sleep(0)

    await polygon_ws_publisher.start()
    await asyncio.wait_for(received_evt.wait(), timeout=2.0)
    await consumer_task

    assert call_count["n"] >= 2  # reconnected at least once


@pytest.mark.asyncio
async def test_shutdown_cancels_running_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch, enabled=True, key=True)

    async def fake_stream(symbols, on_tick):
        await asyncio.Event().wait()  # block forever

    monkeypatch.setattr(
        polygon_ws_publisher.polygon_service,
        "_run_sdk_stream",
        fake_stream,
    )

    await polygon_ws_publisher.start()
    assert polygon_ws_publisher.is_running()

    await polygon_ws_publisher.shutdown()
    assert not polygon_ws_publisher.is_running()


@pytest.mark.asyncio
async def test_shutdown_is_idempotent() -> None:
    await polygon_ws_publisher.shutdown()
    await polygon_ws_publisher.shutdown()  # must not raise


@pytest.mark.asyncio
async def test_start_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable(monkeypatch, enabled=True, key=True)

    async def fake_stream(symbols, on_tick):
        await asyncio.Event().wait()

    monkeypatch.setattr(
        polygon_ws_publisher.polygon_service,
        "_run_sdk_stream",
        fake_stream,
    )

    await polygon_ws_publisher.start()
    first_task = polygon_ws_publisher._task  # noqa: SLF001
    await polygon_ws_publisher.start()
    second_task = polygon_ws_publisher._task  # noqa: SLF001
    assert first_task is second_task


@pytest.mark.asyncio
async def test_publish_tick_skips_missing_symbol() -> None:
    """A payload without 'symbol' must not crash the publisher path."""
    await polygon_ws_publisher._publish_tick({})  # noqa: SLF001
    await polygon_ws_publisher._publish_tick({"price": 100.0})  # noqa: SLF001
    # No assertion — must just not raise.
