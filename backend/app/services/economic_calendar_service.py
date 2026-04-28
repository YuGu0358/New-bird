"""Economic event calendar service.

Reads the curated seed list from `core.economic_calendar.seed_data` and
filters by date range + impact. The service is intentionally simple: no DB
caching is needed for static data, and live enrichment via
TradingEconomics is left as a TODO for a follow-up task once a key is wired.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.economic_calendar import get_seed_events


VALID_IMPACTS = ("high", "medium", "low")


def _parse_iso(s: str) -> datetime:
    # Seed events are timezone-naive UTC; force tz=UTC for downstream
    # comparisons to avoid mixed-aware/naive arithmetic.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def list_upcoming_events(
    *,
    days_ahead: int = 30,
    impact_filter: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return calendar events within the next `days_ahead` days.

    Args:
        days_ahead: forward window in days (1..365).
        impact_filter: "high" / "medium" / "low" or None for all.
        now: override "now" — used by tests for determinism.

    Returns:
        Dict matching EconomicCalendarResponse: {items, as_of}.
    """
    days_ahead = max(1, min(int(days_ahead or 30), 365))

    if impact_filter and impact_filter not in VALID_IMPACTS:
        raise ValueError(
            f"impact_filter must be one of {VALID_IMPACTS!r}, got {impact_filter!r}"
        )

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    horizon_seconds = days_ahead * 86_400

    items: list[dict[str, Any]] = []
    for evt in get_seed_events():
        dt = _parse_iso(evt["date_utc"])
        delta = (dt - current).total_seconds()
        if delta < 0 or delta > horizon_seconds:
            continue
        if impact_filter and evt["impact"] != impact_filter:
            continue
        # Pydantic will parse the ISO string back into datetime, so we keep
        # the original string for serialisation determinism.
        items.append({**evt, "date_utc": dt})

    items.sort(key=lambda e: e["date_utc"])
    return {"items": items, "as_of": current}
