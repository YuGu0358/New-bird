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


@pytest.mark.asyncio
async def test_sse_stream_delivers_published_events() -> None:
    """End-to-end: drive the SSE async-generator directly with a fake Request.

    HTTP-level integration is hard to drive from pytest because the
    streaming response and the publisher share an event loop and the
    httpx + ASGITransport combo has been observed to deadlock in CI.
    Instead, exercise the same `_stream(...)` generator the router uses,
    which gives us per-chunk visibility without spinning up an ASGI loop.
    """
    from app.routers.datahub import _stream as datahub_stream

    datahub_service.register_topic(Topic(name="market:quote:SPY"))

    class _FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    gen = datahub_stream("market:quote:*", _FakeRequest())  # type: ignore[arg-type]

    # First chunk must be the ":connected" preamble.
    first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert b"connected" in first

    # Now publish; the next yielded chunk should carry the payload.
    await datahub_service.publish("market:quote:SPY", {"price": 410.0})

    next_chunk = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert b'"price": 410.0' in next_chunk
    assert next_chunk.startswith(b"event: market:quote:SPY")

    # Cleanup — close the generator so the subscription is unsubscribed.
    await gen.aclose()


@pytest.mark.asyncio
async def test_legacy_stream_url_still_works() -> None:
    """`GET /api/stream/quote:SPY` should keep delivering `market:quote:SPY`
    publishes for a transition window.

    Driven by calling the legacy router's `_stream` async generator
    directly with a fake Request — same pattern as the datahub SSE
    test, for the same deadlock-avoidance reason.
    """
    from app.routers.stream import _stream as legacy_stream

    datahub_service.register_topic(Topic(name="market:quote:SPY"))

    class _FakeRequest:
        async def is_disconnected(self) -> bool:
            return False

    gen = legacy_stream("quote:SPY", _FakeRequest())  # type: ignore[arg-type]
    first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert b"connected" in first

    await datahub_service.publish("market:quote:SPY", {"price": 1.0})
    next_chunk = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
    assert b'"price": 1.0' in next_chunk
    # Legacy URL preserves the legacy short-name in the SSE event field.
    assert next_chunk.startswith(b"event: quote:SPY")

    await gen.aclose()
