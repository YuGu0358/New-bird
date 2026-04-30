"""Per-symbol enriched context — same data the AI Council sees.

Purpose: let the user inspect, in the UI, the exact bundle of evidence
that the LLM is given (price, technicals, volume profile, options flow,
sector regime, …) so they can sanity-check a verdict before acting on it.

This router is intentionally thin — it just calls LiveContextBuilder and
returns the dataclass tree as a JSON-serializable dict. No persistence,
no caching beyond what the underlying services already do.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.services.agents_service import LiveContextBuilder

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


@router.get("/{symbol}/context")
async def get_symbol_context(symbol: str) -> dict[str, Any]:
    """Return the full enriched AnalysisContext for `symbol` as a dict.

    Shape mirrors core.agents.context.AnalysisContext — see that module
    for the full field list. Each channel may be null when the underlying
    service couldn't produce data.
    """
    cleaned = (symbol or "").strip().upper()
    if not cleaned:
        raise HTTPException(status_code=400, detail="symbol is required")
    builder = LiveContextBuilder()
    try:
        ctx = await builder.build(cleaned)
    except Exception as exc:  # pragma: no cover - defensive
        raise service_error(exc) from exc
    return _context_to_dict(ctx)


def _context_to_dict(ctx: Any) -> dict[str, Any]:
    """Convert AnalysisContext + nested dataclasses → JSON-friendly dict.

    asdict() handles nested dataclasses recursively but doesn't ISO-format
    datetime; we coerce the two known datetime fields manually.
    """
    payload = asdict(ctx)
    if "generated_at" in payload and hasattr(payload["generated_at"], "isoformat"):
        payload["generated_at"] = payload["generated_at"].isoformat()
    for item in payload.get("recent_news") or []:
        at = item.get("at")
        if at is not None and hasattr(at, "isoformat"):
            item["at"] = at.isoformat()
    return payload
