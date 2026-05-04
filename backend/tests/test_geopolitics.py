"""Tests for geopolitical risk events service.

Pure-compute coverage over the seed list: filter shapes, severity floor,
window math, sort order, and validation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import geopolitics_service
from core.geopolitics import EVENT_CATEGORIES, REGIONS, get_seed_events


# Anchor every test at a fixed instant inside the seed window so the suite
# isn't calendar-dependent.
NOW = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_returns_full_canonical_lists():
    """The response always echoes back the canonical region+category lists
    so the UI can render dropdowns from a single source of truth."""
    payload = await geopolitics_service.list_events(
        days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert payload["regions"] == list(REGIONS)
    assert payload["categories"] == list(EVENT_CATEGORIES)


@pytest.mark.asyncio
async def test_default_window_returns_some_events():
    """A reasonable default window picks up most of the seed list."""
    payload = await geopolitics_service.list_events(now=NOW)
    assert payload["total"] > 0
    assert len(payload["items"]) == payload["total"]


@pytest.mark.asyncio
async def test_region_filter_exact_match():
    payload = await geopolitics_service.list_events(
        region="middle_east", days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["region"] == "middle_east"


@pytest.mark.asyncio
async def test_category_filter_exact_match():
    payload = await geopolitics_service.list_events(
        category="sanctions", days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["category"] == "sanctions"


@pytest.mark.asyncio
async def test_min_severity_floor_excludes_low_severity():
    payload = await geopolitics_service.list_events(
        min_severity=70, days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert payload["total"] > 0
    for item in payload["items"]:
        assert item["severity"] >= 70


@pytest.mark.asyncio
async def test_invalid_region_raises_value_error():
    with pytest.raises(ValueError, match="region must be one of"):
        await geopolitics_service.list_events(region="atlantis", now=NOW)


@pytest.mark.asyncio
async def test_invalid_category_raises_value_error():
    with pytest.raises(ValueError, match="category must be one of"):
        await geopolitics_service.list_events(category="cyber-war", now=NOW)


@pytest.mark.asyncio
async def test_window_filters_old_events():
    """A 0-day-back window shouldn't return events that occurred before NOW."""
    payload = await geopolitics_service.list_events(
        days_back=0, days_ahead=365 * 5, now=NOW
    )
    for item in payload["items"]:
        assert item["date_utc"] >= NOW


@pytest.mark.asyncio
async def test_window_filters_future_events():
    """A 0-day-ahead window shouldn't return events in the future."""
    payload = await geopolitics_service.list_events(
        days_back=365 * 5, days_ahead=0, now=NOW
    )
    for item in payload["items"]:
        assert item["date_utc"] <= NOW


@pytest.mark.asyncio
async def test_items_sorted_by_severity_desc_then_date_desc():
    """Highest-severity events come first; ties break on most recent."""
    payload = await geopolitics_service.list_events(
        days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    items = payload["items"]
    assert len(items) >= 2
    for a, b in zip(items, items[1:]):
        if a["severity"] == b["severity"]:
            assert a["date_utc"] >= b["date_utc"]
        else:
            assert a["severity"] > b["severity"]


@pytest.mark.asyncio
async def test_severity_clamped_to_valid_range():
    """min_severity=999 → no events; min_severity=-1 → all events (treated as 0)."""
    none_match = await geopolitics_service.list_events(
        min_severity=999, days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert none_match["total"] == 0

    all_match = await geopolitics_service.list_events(
        min_severity=-1, days_back=365 * 5, days_ahead=365 * 5, now=NOW
    )
    assert all_match["total"] > 0


@pytest.mark.asyncio
async def test_combined_filters_intersect():
    """region + category + severity floor compose AND, not OR."""
    payload = await geopolitics_service.list_events(
        region="middle_east",
        category="armed_conflict",
        min_severity=60,
        days_back=365 * 5,
        days_ahead=365 * 5,
        now=NOW,
    )
    for item in payload["items"]:
        assert item["region"] == "middle_east"
        assert item["category"] == "armed_conflict"
        assert item["severity"] >= 60


def test_seed_data_has_at_least_25_events():
    """Sanity check on the curated list size."""
    seeds = get_seed_events()
    assert len(seeds) >= 25


def test_seed_data_severity_within_bounds():
    for evt in get_seed_events():
        sev = int(evt["severity"])
        assert 0 <= sev <= 100, f"severity out of range for {evt['id']}"


def test_seed_data_unique_ids():
    seeds = get_seed_events()
    ids = [evt["id"] for evt in seeds]
    assert len(ids) == len(set(ids)), "duplicate event ids detected"


def test_seed_data_uses_canonical_regions_and_categories():
    for evt in get_seed_events():
        assert evt["region"] in REGIONS, f"unknown region {evt['region']!r} in {evt['id']}"
        assert evt["category"] in EVENT_CATEGORIES, (
            f"unknown category {evt['category']!r} in {evt['id']}"
        )
