"""Metrics primitives + Prometheus rendering."""
from __future__ import annotations

import pytest

from core.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    render_prometheus,
)


def test_counter_inc() -> None:
    c = Counter("http_requests_total", "HTTP requests served")
    assert c.value == 0
    c.inc()
    c.inc(2.5)
    assert c.value == 3.5


def test_gauge_set_and_inc() -> None:
    g = Gauge("active_websockets", "Open websocket count")
    g.set(5)
    g.inc(2)
    g.dec(1)
    assert g.value == 6


def test_histogram_buckets_and_count() -> None:
    h = Histogram("request_duration_seconds", "Request duration", buckets=[0.1, 0.5, 1.0])
    h.observe(0.05)  # falls in 0.1
    h.observe(0.3)   # falls in 0.5
    h.observe(0.8)   # falls in 1.0
    h.observe(2.0)   # +Inf
    assert h.count == 4
    assert pytest.approx(h.sum) == pytest.approx(0.05 + 0.3 + 0.8 + 2.0)
    assert h.bucket_counts[0.1] == 1
    assert h.bucket_counts[0.5] == 2
    assert h.bucket_counts[1.0] == 3


def test_render_prometheus_includes_help_and_type() -> None:
    registry = MetricsRegistry()
    counter = registry.counter("events_total", "Test events")
    counter.inc(7)
    output = render_prometheus(registry)
    assert "# HELP events_total Test events" in output
    assert "# TYPE events_total counter" in output
    assert "events_total 7.0" in output


def test_render_prometheus_histogram() -> None:
    registry = MetricsRegistry()
    h = registry.histogram("latency_seconds", "Latency", buckets=[0.1, 1.0])
    h.observe(0.05)
    h.observe(0.5)
    output = render_prometheus(registry)
    assert "# TYPE latency_seconds histogram" in output
    assert 'latency_seconds_bucket{le="0.1"} 1' in output
    assert 'latency_seconds_bucket{le="1.0"} 2' in output
    assert 'latency_seconds_bucket{le="+Inf"} 2' in output
    assert "latency_seconds_count 2" in output
