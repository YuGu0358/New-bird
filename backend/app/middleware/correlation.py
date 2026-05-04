"""Mints or reuses an X-Request-ID and stores it in the correlation-id ContextVar."""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from core.observability.correlation import correlation_id_var


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    HEADER_NAME = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get(self.HEADER_NAME, "").strip()
        request_id = incoming or uuid.uuid4().hex
        token = correlation_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers[self.HEADER_NAME] = request_id
        return response
