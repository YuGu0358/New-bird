"""Geopolitical risk events service.

Reads the curated seed list and filters by region / category / severity floor
/ time window. The service is intentionally simple: no DB caching needed for
static data, and live ACLED / HDX enrichment is a follow-up task once API
keys / rate-limit handling are designed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from core.geopolitics import EVENT_CATEGORIES, REGIONS, get_seed_events


def _parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


async def list_events(
    *,
    region: str | None = None,
    category: str | None = None,
    min_severity: int = 0,
    days_back: int = 365,
    days_ahead: int = 365,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return curated geopolitical events filtered by the supplied params.

    Args:
        region: Restrict to one canonical region (must be in REGIONS) or None.
        category: Restrict to one canonical category (must be in EVENT_CATEGORIES) or None.
        min_severity: Drop events whose severity score is below this (0..100).
        days_back: Look-back window in days from `now`. Capped at 365 * 5.
        days_ahead: Look-ahead window in days from `now`. Capped at 365 * 5.
        now: Reference instant — tests pass a fixed datetime for determinism.

    Returns dict shape: {items, as_of, total, regions, categories}.
    """
    if region is not None and region not in REGIONS:
        raise ValueError(f"region must be one of {REGIONS!r}, got {region!r}")
    if category is not None and category not in EVENT_CATEGORIES:
        raise ValueError(
            f"category must be one of {EVENT_CATEGORIES!r}, got {category!r}"
        )

    severity_floor = max(0, min(int(min_severity or 0), 100))
    back = max(0, min(int(days_back or 0), 365 * 5))
    ahead = max(0, min(int(days_ahead or 0), 365 * 5))

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    earliest = current - timedelta(days=back)
    latest = current + timedelta(days=ahead)

    items: list[dict[str, Any]] = []
    for evt in get_seed_events():
        when = _parse_iso(str(evt["date_utc"]))
        if when < earliest or when > latest:
            continue
        if region is not None and evt.get("region") != region:
            continue
        if category is not None and evt.get("category") != category:
            continue
        if int(evt.get("severity", 0)) < severity_floor:
            continue
        items.append(
            {
                "id": evt["id"],
                "date_utc": when,
                "title": evt["title"],
                "region": evt["region"],
                "category": evt["category"],
                "severity": int(evt["severity"]),
                "asset_classes": list(evt.get("asset_classes") or ()),
                "summary": evt.get("summary", ""),
                "source": evt.get("source", "seed"),
            }
        )

    # Sort by severity desc, then by date desc — UI surfaces highest-impact first.
    items.sort(key=lambda e: (-int(e["severity"]), -e["date_utc"].timestamp()))
    return {
        "items": items,
        "as_of": current,
        "total": len(items),
        "regions": list(REGIONS),
        "categories": list(EVENT_CATEGORIES),
    }
