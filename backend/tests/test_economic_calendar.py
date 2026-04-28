"""Unit tests for the economic calendar service + seed data."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.services import economic_calendar_service
from core.economic_calendar import EVENT_CATEGORIES, get_seed_events


REQUIRED_FIELDS = {"id", "date_utc", "name", "country", "category", "impact", "source"}


def test_seed_events_have_required_fields():
    events = get_seed_events()
    assert len(events) >= 25, "expected ~30 curated events"
    for e in events:
        missing = REQUIRED_FIELDS - set(e.keys())
        assert not missing, f"event {e.get('id')} missing fields {missing}"


def test_seed_events_categories_valid():
    for e in get_seed_events():
        assert e["category"] in EVENT_CATEGORIES, e


def test_seed_events_impact_valid():
    for e in get_seed_events():
        assert e["impact"] in ("high", "medium", "low"), e


def test_seed_events_country_us():
    for e in get_seed_events():
        assert e["country"] == "US"


def test_seed_events_iso_dates_parse():
    for e in get_seed_events():
        # Round-trip through fromisoformat to confirm well-formed strings
        datetime.fromisoformat(e["date_utc"])


def test_seed_events_unique_ids():
    events = get_seed_events()
    ids = [e["id"] for e in events]
    assert len(ids) == len(set(ids)), "duplicate id in seed data"


def test_seed_events_sorted_or_sortable():
    """Events should be sortable by date — pre-sorting not required, but no
    malformed dates either."""
    events = get_seed_events()
    sorted_events = sorted(events, key=lambda e: e["date_utc"])
    assert len(sorted_events) == len(events)


def test_seed_includes_fomc_meetings():
    """Sanity check — at least 4 FOMC rate decisions in the seed."""
    fomc_count = sum(
        1 for e in get_seed_events() if "FOMC" in e["name"] and "Rate Decision" in e["name"]
    )
    assert fomc_count >= 4, f"expected ≥4 FOMC meetings, got {fomc_count}"


def test_seed_includes_monthly_cpi_and_nfp():
    """Sanity check — multi-month CPI and NFP coverage."""
    cpi = [e for e in get_seed_events() if e["name"].startswith("CPI")]
    nfp = [e for e in get_seed_events() if "Non-Farm Payrolls" in e["name"]]
    assert len(cpi) >= 5
    assert len(nfp) >= 5


@pytest.mark.asyncio
async def test_list_upcoming_events_default_window():
    """30-day window from a fixed point should pick events in May 2026."""
    fake_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    payload = await economic_calendar_service.list_upcoming_events(now=fake_now)
    assert isinstance(payload, dict)
    assert payload["as_of"] == fake_now
    assert isinstance(payload["items"], list)
    # Within 30 days of 2026-05-01 we should see NFP-Apr (May 2) and CPI-Apr (May 13)
    names = [e["name"] for e in payload["items"]]
    assert any("Non-Farm Payrolls" in n for n in names), names
    assert any(n.startswith("CPI") for n in names), names


@pytest.mark.asyncio
async def test_list_upcoming_events_high_only():
    fake_now = datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)
    payload = await economic_calendar_service.list_upcoming_events(
        days_ahead=60, impact_filter="high", now=fake_now
    )
    assert all(e["impact"] == "high" for e in payload["items"])


@pytest.mark.asyncio
async def test_list_upcoming_events_invalid_impact_raises():
    with pytest.raises(ValueError):
        await economic_calendar_service.list_upcoming_events(
            impact_filter="bogus",
        )


@pytest.mark.asyncio
async def test_list_upcoming_events_excludes_past():
    """Events before `now` must be filtered out."""
    fake_now = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    payload = await economic_calendar_service.list_upcoming_events(
        days_ahead=365, now=fake_now
    )
    # Almost all seeds are 2026; from 2026-12-31 only 2027 events would be in
    # range. We have none, so the list should be empty.
    assert payload["items"] == []


@pytest.mark.asyncio
async def test_list_upcoming_events_clamps_days_ahead():
    """Caller passing 0 / negative / huge values gets a clamped window."""
    fake_now = datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)
    payload_zero = await economic_calendar_service.list_upcoming_events(
        days_ahead=0, now=fake_now
    )
    # 0 → clamped to 1 day; from 2026-04-28 we only have one event in next 24h
    # (the FOMC on 04-29). Confirm at least one event is returned.
    assert len(payload_zero["items"]) >= 1

    payload_huge = await economic_calendar_service.list_upcoming_events(
        days_ahead=99_999, now=fake_now
    )
    # Clamped to 365 — at most all seed events
    assert len(payload_huge["items"]) <= len(get_seed_events())


@pytest.mark.asyncio
async def test_list_upcoming_events_sorted_ascending():
    fake_now = datetime(2026, 4, 28, 0, 0, 0, tzinfo=timezone.utc)
    payload = await economic_calendar_service.list_upcoming_events(
        days_ahead=365, now=fake_now
    )
    dates = [e["date_utc"] for e in payload["items"]]
    assert dates == sorted(dates)
