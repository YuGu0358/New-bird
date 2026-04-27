"""Hand-rolled Prometheus-compatible metrics primitives.

Stays dependency-free. The set of metric types here covers what Phase 5
needs: a global counter store, a small set of gauges, two latency
histograms. If we ever outgrow this, swap it for the official
`prometheus-client` package — the emitted exposition format already matches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from threading import Lock
from typing import Iterable


@dataclass
class Counter:
    name: str
    help_text: str
    value: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter cannot decrease.")
        with self._lock:
            self.value += amount


@dataclass
class Gauge:
    name: str
    help_text: str
    value: float = 0.0
    _lock: Lock = field(default_factory=Lock, repr=False)

    def set(self, value: float) -> None:
        with self._lock:
            self.value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self.value -= amount


@dataclass
class Histogram:
    name: str
    help_text: str
    buckets: list[float]
    count: int = 0
    sum: float = 0.0
    bucket_counts: dict[float, int] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        # Ensure buckets are sorted and the +Inf bucket exists.
        self.buckets = sorted(self.buckets)
        for b in self.buckets:
            self.bucket_counts[b] = 0
        self.bucket_counts[math.inf] = 0

    def observe(self, value: float) -> None:
        with self._lock:
            self.count += 1
            self.sum += value
            for b in self.buckets:
                if value <= b:
                    self.bucket_counts[b] += 1
            self.bucket_counts[math.inf] += 1


class MetricsRegistry:
    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}

    def counter(self, name: str, help_text: str) -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name=name, help_text=help_text)
        return self._counters[name]

    def gauge(self, name: str, help_text: str) -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name=name, help_text=help_text)
        return self._gauges[name]

    def histogram(
        self,
        name: str,
        help_text: str,
        *,
        buckets: Iterable[float] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    ) -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name=name, help_text=help_text, buckets=list(buckets))
        return self._histograms[name]

    def all(self) -> tuple[list[Counter], list[Gauge], list[Histogram]]:
        return (
            list(self._counters.values()),
            list(self._gauges.values()),
            list(self._histograms.values()),
        )


default_registry = MetricsRegistry()


def _format_bucket_le(value: float) -> str:
    return "+Inf" if value == math.inf else f"{value}"


def render_prometheus(registry: MetricsRegistry = default_registry) -> str:
    lines: list[str] = []
    counters, gauges, histograms = registry.all()

    for c in counters:
        lines.append(f"# HELP {c.name} {c.help_text}")
        lines.append(f"# TYPE {c.name} counter")
        lines.append(f"{c.name} {float(c.value)}")

    for g in gauges:
        lines.append(f"# HELP {g.name} {g.help_text}")
        lines.append(f"# TYPE {g.name} gauge")
        lines.append(f"{g.name} {float(g.value)}")

    for h in histograms:
        lines.append(f"# HELP {h.name} {h.help_text}")
        lines.append(f"# TYPE {h.name} histogram")
        for bucket, count in h.bucket_counts.items():
            le = _format_bucket_le(bucket)
            lines.append(f'{h.name}_bucket{{le="{le}"}} {int(count)}')
        lines.append(f"{h.name}_count {int(h.count)}")
        lines.append(f"{h.name}_sum {float(h.sum)}")

    return "\n".join(lines) + "\n"
