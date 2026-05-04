"""Prometheus metrics exposition endpoint.

Convention is to expose metrics at `/metrics` (NOT `/api/metrics`) so
generic Prometheus scrapers find it without prefix configuration.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from core.observability.metrics import render_prometheus

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def get_metrics() -> str:
    return render_prometheus()
