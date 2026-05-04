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
