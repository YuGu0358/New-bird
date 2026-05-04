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
