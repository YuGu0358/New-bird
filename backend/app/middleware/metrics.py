"""ASGI middleware: count requests + record latency."""
from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from core.observability.metrics import default_registry


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._requests_total = default_registry.counter(
            "http_requests_total", "Total HTTP requests served"
        )
        self._latency = default_registry.histogram(
            "http_request_duration_seconds", "HTTP request duration in seconds"
        )

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            self._latency.observe(time.perf_counter() - start)
            self._requests_total.inc()
        return response
