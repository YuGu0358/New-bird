"""Service-layer tests for the investment journal CRUD + autocomplete.

Written TDD-first against the public surface in
`app.services.journal_service` per Task 2 of the journal plan.
"""
from __future__ import annotations

import asyncio

import pytest

from app.database import AsyncSessionLocal, JournalEntry


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so JournalEntry rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "journal.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


# ---------------------------------------------------------------------------
# create + list happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_list_returns_entry() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        created = await journal_service.create_entry(
            session,
            title="First note",
            body="thoughts on NVDA",
            symbols=["nvda"],
            mood="bullish",
        )
        assert created["id"] > 0
        assert created["title"] == "First note"
        assert created["body"] == "thoughts on NVDA"
        assert created["symbols"] == ["NVDA"]
        assert created["mood"] == "bullish"
        assert created["created_at"] is not None

        rows = await journal_service.list_entries(session)
        assert len(rows) == 1
        assert rows[0]["id"] == created["id"]
        assert rows[0]["title"] == "First note"


# ---------------------------------------------------------------------------
# list newest-first ordering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_newest_first() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        a = await journal_service.create_entry(session, title="Older", body="A")
        await asyncio.sleep(0.02)
        b = await journal_service.create_entry(session, title="Newer", body="B")
        await asyncio.sleep(0.02)
        c = await journal_service.create_entry(session, title="Newest", body="C")

        rows = await journal_service.list_entries(session)
        assert [r["id"] for r in rows] == [c["id"], b["id"], a["id"]]


# ---------------------------------------------------------------------------
# list filtered by symbol — JSON contains via LIKE without false-positive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filtered_by_symbol_no_false_match() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        nvda = await journal_service.create_entry(
            session, title="On NVDA", body="x", symbols=["NVDA"]
        )
        await journal_service.create_entry(
            session, title="On NVDA-Inverse", body="y", symbols=["NVDA-Inverse"]
        )
        await journal_service.create_entry(
            session, title="Other", body="z", symbols=["TSLA", "AAPL"]
        )
        nvda_with_aapl = await journal_service.create_entry(
            session, title="Mixed", body="w", symbols=["AAPL", "NVDA"]
        )

        results = await journal_service.list_entries(session, symbol="NVDA")
        ids = {r["id"] for r in results}
        # Exactly the two real NVDA entries — NVDA-Inverse must NOT slip in.
        assert ids == {nvda["id"], nvda_with_aapl["id"]}

        # Case-insensitive on the input symbol.
        results_lower = await journal_service.list_entries(session, symbol="nvda")
        assert {r["id"] for r in results_lower} == ids


# ---------------------------------------------------------------------------
# list filtered by mood
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filtered_by_mood() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        await journal_service.create_entry(session, title="bull", body="x", mood="bullish")
        await journal_service.create_entry(session, title="bear", body="y", mood="bearish")
        await journal_service.create_entry(session, title="neut", body="z", mood="neutral")
        await journal_service.create_entry(session, title="bull2", body="w", mood="bullish")

        rows = await journal_service.list_entries(session, mood="bullish")
        assert len(rows) == 2
        assert all(r["mood"] == "bullish" for r in rows)


# ---------------------------------------------------------------------------
# list search across title and body, case-insensitive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_search_matches_title_and_body_case_insensitive() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        a = await journal_service.create_entry(
            session, title="Earnings Drift", body="something else"
        )
        b = await journal_service.create_entry(
            session, title="Macro view", body="we need to track the EARNINGS cycle"
        )
        await journal_service.create_entry(session, title="Other", body="nothing here")

        rows = await journal_service.list_entries(session, search="earnings")
        ids = {r["id"] for r in rows}
        assert ids == {a["id"], b["id"]}

        rows_upper = await journal_service.list_entries(session, search="EARNINGS")
        assert {r["id"] for r in rows_upper} == ids


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_pagination_with_limit_offset() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        ids = []
        for i in range(5):
            row = await journal_service.create_entry(session, title=f"n{i}", body="x")
            ids.append(row["id"])
            await asyncio.sleep(0.01)

        page1 = await journal_service.list_entries(session, limit=2, offset=0)
        page2 = await journal_service.list_entries(session, limit=2, offset=2)
        page3 = await journal_service.list_entries(session, limit=2, offset=4)

        # newest-first: ids[4], ids[3], ids[2], ids[1], ids[0]
        assert [r["id"] for r in page1] == [ids[4], ids[3]]
        assert [r["id"] for r in page2] == [ids[2], ids[1]]
        assert [r["id"] for r in page3] == [ids[0]]

        # limit clamping: 0 / huge values get clamped into [1, 200]
        clamped_low = await journal_service.list_entries(session, limit=0)
        assert len(clamped_low) == 1
        clamped_high = await journal_service.list_entries(session, limit=10_000)
        assert len(clamped_high) == 5  # only 5 entries exist


# ---------------------------------------------------------------------------
# update is true PATCH
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_only_changes_passed_fields() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        original = await journal_service.create_entry(
            session,
            title="Original",
            body="original body",
            symbols=["NVDA"],
            mood="bullish",
        )

        # Patch title only — body / symbols / mood untouched.
        patched = await journal_service.update_entry(
            session, original["id"], title="Updated"
        )
        assert patched is not None
        assert patched["title"] == "Updated"
        assert patched["body"] == "original body"
        assert patched["symbols"] == ["NVDA"]
        assert patched["mood"] == "bullish"

        # Patch symbols only — they should be normalized + deduplicated.
        patched2 = await journal_service.update_entry(
            session, original["id"], symbols=["aapl", "AAPL", "tsla"]
        )
        assert patched2["symbols"] == ["AAPL", "TSLA"]
        assert patched2["title"] == "Updated"

        # Patch with empty list resets to []
        patched3 = await journal_service.update_entry(
            session, original["id"], symbols=[]
        )
        assert patched3["symbols"] == []

        # Missing entry returns None.
        assert await journal_service.update_entry(session, 999_999, title="x") is None


# ---------------------------------------------------------------------------
# delete + 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_entry_and_returns_bool() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        created = await journal_service.create_entry(session, title="Delete me", body="x")
        assert await journal_service.delete_entry(session, created["id"]) is True
        assert await journal_service.get_entry(session, created["id"]) is None
        # Second delete: row is gone, must return False.
        assert await journal_service.delete_entry(session, created["id"]) is False


# ---------------------------------------------------------------------------
# mood validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mood_validation_rejects_unknown_values() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await journal_service.create_entry(
                session, title="bad", body="x", mood="ecstatic"
            )

        # All four canonical moods are accepted.
        for good in ("bullish", "bearish", "neutral", "watching"):
            row = await journal_service.create_entry(
                session, title=f"m-{good}", body="x", mood=good
            )
            assert row["mood"] == good

        # update_entry must enforce the same rule.
        existing = await journal_service.create_entry(session, title="patch", body="x")
        with pytest.raises(ValueError):
            await journal_service.update_entry(session, existing["id"], mood="weird")


# ---------------------------------------------------------------------------
# title validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_title_validation_rejects_empty_and_whitespace() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await journal_service.create_entry(session, title="", body="x")
        with pytest.raises(ValueError):
            await journal_service.create_entry(session, title="   \t\n  ", body="x")

        # Title is trimmed and capped at 120 chars.
        long = "a" * 200
        row = await journal_service.create_entry(session, title=f"  {long}  ", body="x")
        assert row["title"] == long[:120]
        assert len(row["title"]) == 120

        # update_entry: empty / whitespace title is also rejected.
        with pytest.raises(ValueError):
            await journal_service.update_entry(session, row["id"], title="   ")


# ---------------------------------------------------------------------------
# symbol normalization + 20-cap
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_symbol_normalization_dedupe_and_cap() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        row = await journal_service.create_entry(
            session,
            title="syms",
            body="x",
            symbols=["nvda", "NVDA", " aapl ", "tsla", "AAPL"],
        )
        assert row["symbols"] == ["NVDA", "AAPL", "TSLA"]

        # Over-cap rejected on create.
        with pytest.raises(ValueError):
            await journal_service.create_entry(
                session, title="too many", body="x",
                symbols=[f"S{i}" for i in range(21)],
            )

        # Over-cap rejected on update too.
        with pytest.raises(ValueError):
            await journal_service.update_entry(
                session, row["id"],
                symbols=[f"S{i}" for i in range(25)],
            )


# ---------------------------------------------------------------------------
# autocomplete_symbols
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_autocomplete_symbols_returns_distinct_uppercased_matches() -> None:
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        await journal_service.create_entry(
            session, title="a", body="x", symbols=["NVDA", "TSLA"]
        )
        await journal_service.create_entry(
            session, title="b", body="x", symbols=["nvda", "NVO"]
        )
        await journal_service.create_entry(
            session, title="c", body="x", symbols=["AAPL"]
        )

        # 'n' / 'N' both find NVDA + NVO, distinct.
        out = await journal_service.autocomplete_symbols(session, prefix="n")
        assert sorted(out) == ["NVDA", "NVO"]

        out_upper = await journal_service.autocomplete_symbols(session, prefix="N")
        assert sorted(out_upper) == ["NVDA", "NVO"]

        # 'NV' narrows further but still distinct (NVDA appears twice in storage).
        out_nv = await journal_service.autocomplete_symbols(session, prefix="NV")
        assert sorted(out_nv) == ["NVDA", "NVO"]

        # Empty prefix returns all distinct symbols, capped by limit.
        out_all = await journal_service.autocomplete_symbols(session, prefix="", limit=10)
        assert sorted(out_all) == ["AAPL", "NVDA", "NVO", "TSLA"]

        # Limit is honored.
        out_lim = await journal_service.autocomplete_symbols(session, prefix="", limit=2)
        assert len(out_lim) == 2

        # No matches -> empty.
        empty = await journal_service.autocomplete_symbols(session, prefix="ZZZ")
        assert empty == []


# ---------------------------------------------------------------------------
# LIKE-wildcard escaping in list filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filtered_by_symbol_does_not_match_like_wildcards() -> None:
    """Symbol filter '_' must not match every single entry (where _ would
    otherwise match any character in LIKE)."""
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        await journal_service.create_entry(
            session, title="a", body="x", symbols=["NVDA"]
        )
        await journal_service.create_entry(
            session, title="b", body="y", symbols=["TSLA"]
        )
        await journal_service.create_entry(
            session, title="c", body="z", symbols=["AAPL", "MSFT"]
        )

        # No symbol contains a literal underscore — this must return zero,
        # not every row.
        results = await journal_service.list_entries(session, symbol="_")
        assert len(results) == 0

        # Same for the % wildcard.
        results_pct = await journal_service.list_entries(session, symbol="%")
        assert len(results_pct) == 0


@pytest.mark.asyncio
async def test_count_entries_matches_list_filters() -> None:
    """`count_entries` must apply the same WHERE clauses as `list_entries`,
    so paginated UIs can show "showing N of total" without lying."""
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        await journal_service.create_entry(
            session, title="bull-nvda", body="x",
            symbols=["NVDA"], mood="bullish",
        )
        await journal_service.create_entry(
            session, title="bear-nvda", body="y",
            symbols=["NVDA"], mood="bearish",
        )
        await journal_service.create_entry(
            session, title="bull-tsla", body="earnings up",
            symbols=["TSLA"], mood="bullish",
        )

        # Unfiltered: matches all rows.
        assert await journal_service.count_entries(session) == 3

        # By symbol — exactly the two NVDA rows.
        assert await journal_service.count_entries(session, symbol="NVDA") == 2

        # By mood — the two bullish rows.
        assert await journal_service.count_entries(session, mood="bullish") == 2

        # Combined symbol + mood — only the bull-nvda row.
        assert await journal_service.count_entries(
            session, symbol="NVDA", mood="bullish"
        ) == 1

        # Search hits title or body, case-insensitive.
        assert await journal_service.count_entries(session, search="earnings") == 1

        # No matches — must be 0, not the unfiltered total.
        assert await journal_service.count_entries(session, symbol="ZZZ") == 0


@pytest.mark.asyncio
async def test_count_entries_ignores_pagination_args() -> None:
    """`count_entries` deliberately has no `limit`/`offset` — it always
    returns the total matching the filters. Make that explicit in a test
    so a future refactor doesn't accidentally apply limit to the count."""
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        for i in range(7):
            await journal_service.create_entry(session, title=f"row{i}", body="x")

        # The list call would clamp to 5 — count should still be 7.
        page = await journal_service.list_entries(session, limit=5)
        assert len(page) == 5
        assert await journal_service.count_entries(session) == 7


@pytest.mark.asyncio
async def test_list_search_does_not_match_like_wildcards() -> None:
    """Search '%foo' must not match titles/bodies that contain the literal
    word but not the % prefix."""
    from app.services import journal_service

    async with AsyncSessionLocal() as session:
        await journal_service.create_entry(session, title="foo", body="alpha")
        await journal_service.create_entry(session, title="bar", body="beta")

        # "%foo" should match only entries containing the literal "%foo"
        # substring — neither test row has that, so result is zero.
        results_pct = await journal_service.list_entries(session, search="%foo")
        assert len(results_pct) == 0

        # Lone "_" must not match every row either.
        results_us = await journal_service.list_entries(session, search="_")
        assert len(results_us) == 0
