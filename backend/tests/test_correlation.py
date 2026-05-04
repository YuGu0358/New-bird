"""Correlation-ID context store + middleware."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.observability.correlation import (
    correlation_id_var,
    get_correlation_id,
    set_correlation_id,
)


def test_default_correlation_id_is_empty_string() -> None:
    # Each test starts with a fresh ContextVar token, so the default holds.
    assert get_correlation_id() == ""


def test_set_and_get() -> None:
    token = set_correlation_id("abc-123")
    try:
        assert get_correlation_id() == "abc-123"
    finally:
        correlation_id_var.reset(token)


def test_middleware_mints_uuid_when_no_header() -> None:
    from app.middleware.correlation import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    async def _echo() -> dict[str, str]:
        return {"id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/echo")
    payload = response.json()
    assert payload["id"]
    assert response.headers.get("X-Request-ID") == payload["id"]


def test_middleware_picks_up_inbound_request_id_header() -> None:
    from app.middleware.correlation import CorrelationIdMiddleware

    app = FastAPI()
    app.add_middleware(CorrelationIdMiddleware)

    @app.get("/echo")
    async def _echo() -> dict[str, str]:
        return {"id": get_correlation_id()}

    client = TestClient(app)
    response = client.get("/echo", headers={"X-Request-ID": "preset-id-42"})
    assert response.json()["id"] == "preset-id-42"
    assert response.headers["X-Request-ID"] == "preset-id-42"
