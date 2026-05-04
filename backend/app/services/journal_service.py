"""Investment-journal service layer: CRUD + symbol autocomplete.

Public surface (all async, all return plain dicts):
    list_entries, get_entry, create_entry, update_entry, delete_entry,
    autocomplete_symbols.

Validation lives here (router will translate `ValueError` to HTTP 400 in
Task 3). The DB schema in `JournalEntry` is permissive on purpose so this
layer is the single source of truth for what an "acceptable" entry looks
like.

JSON containment in SQLite has no portable operator in SQLAlchemy 2.x. We
serialize `symbols` via the JSON column type, then filter using
`LIKE :pat` on the cast-to-text representation with a quoted token —
e.g. `%"NVDA"%`. The wrapping double-quotes are critical so a search for
"NVDA" does not false-match "NVDA-Inverse" et al.
"""
from __future__ import annotations

from typing import Any, Iterable

from sqlalchemy import String, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import JournalEntry


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_MOODS: frozenset[str] = frozenset({"bullish", "bearish", "neutral", "watching"})
TITLE_MAX_LEN: int = 120
SYMBOL_MAX_COUNT: int = 20
LIMIT_MIN: int = 1
LIMIT_MAX: int = 200


# ---------------------------------------------------------------------------
# Validators / normalizers
# ---------------------------------------------------------------------------


def _normalize_title(title: str) -> str:
    """Strip + cap at 120 chars. Empty/whitespace raises ValueError."""
    if title is None:
        raise ValueError("title is required")
    trimmed = str(title).strip()
    if not trimmed:
        raise ValueError("title must not be empty")
    return trimmed[:TITLE_MAX_LEN]


def _normalize_symbols(symbols: Iterable[str] | None) -> list[str]:
    """Upper-case, strip, de-duplicate (preserving first-seen order). Cap at 20."""
    if symbols is None:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for raw in symbols:
        if raw is None:
            continue
        token = str(raw).strip().upper()
        if not token:
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
    if len(out) > SYMBOL_MAX_COUNT:
        raise ValueError(f"symbols capped at {SYMBOL_MAX_COUNT}")
    return out


def _validate_mood(mood: str) -> str:
    if mood not in ALLOWED_MOODS:
        raise ValueError(
            f"mood must be one of {sorted(ALLOWED_MOODS)}, got {mood!r}"
        )
    return mood


def _clamp_limit(limit: int) -> int:
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = LIMIT_MIN
    return max(LIMIT_MIN, min(n, LIMIT_MAX))


def _clamp_offset(offset: int) -> int:
    try:
        n = int(offset)
    except (TypeError, ValueError):
        n = 0
    return max(0, n)


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards (% and _) plus the JSON-quote char (") so that
    `WHERE col LIKE pattern ESCAPE '\\'` matches the literal substring only.

    A user passing `symbol="_"` or `search="%foo"` would otherwise get wrong
    rows because LIKE treats `_` and `%` as wildcards. We also escape `\\`
    itself (must come first) and `"` so the JSON-quoted pattern stays sane.
    """
    return (
        text.replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
            .replace('"', '\\"')
    )


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _serialize(row: JournalEntry) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "body": row.body,
        "symbols": list(row.symbols or []),
        "mood": row.mood,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _apply_list_filters(
    stmt,
    *,
    symbol: str | None,
    mood: str | None,
    search: str | None,
):
    """Apply the standard journal filters (symbol/mood/search) to `stmt`.

    Shared by `list_entries` and `count_entries` so the WHERE clauses stay
    in lockstep — `total` would be a lie if either side drifted.
    """
    if symbol:
        token = str(symbol).strip().upper()
        if token:
            # Quoted literal LIKE on the cast-to-text JSON column. The
            # surrounding double-quotes from the JSON serializer prevent
            # `"NVDA"` from matching `"NVDA-Inverse"`. Escape LIKE wildcards
            # so a user passing `_` or `%` doesn't match every row.
            pattern = f'%"{_escape_like(token)}"%'
            stmt = stmt.where(
                JournalEntry.symbols.cast(String).like(pattern, escape="\\")
            )

    if mood:
        stmt = stmt.where(JournalEntry.mood == mood)

    if search:
        raw = str(search).strip().lower()
        if raw:
            # Escape LIKE wildcards so `%foo` / `_` are treated as literals
            # rather than matching every row.
            needle = f"%{_escape_like(raw)}%"
            stmt = stmt.where(
                or_(
                    func.lower(JournalEntry.title).like(needle, escape="\\"),
                    func.lower(JournalEntry.body).like(needle, escape="\\"),
                )
            )

    return stmt


async def list_entries(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    mood: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List entries newest-first, with optional ANDed filters + pagination."""
    stmt = select(JournalEntry).order_by(
        desc(JournalEntry.created_at), desc(JournalEntry.id)
    )
    stmt = _apply_list_filters(stmt, symbol=symbol, mood=mood, search=search)
    stmt = stmt.limit(_clamp_limit(limit)).offset(_clamp_offset(offset))
    rows = (await session.execute(stmt)).scalars().all()
    return [_serialize(r) for r in rows]


async def count_entries(
    session: AsyncSession,
    *,
    symbol: str | None = None,
    mood: str | None = None,
    search: str | None = None,
) -> int:
    """Count entries matching the same filters as `list_entries`.

    Used by the router to populate `JournalListResponse.total` so paginated
    UIs know how many pages exist. Always returns the unfiltered total when
    no filters are supplied.
    """
    stmt = select(func.count()).select_from(JournalEntry)
    stmt = _apply_list_filters(stmt, symbol=symbol, mood=mood, search=search)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def get_entry(session: AsyncSession, entry_id: int) -> dict[str, Any] | None:
    row = await session.get(JournalEntry, entry_id)
    return _serialize(row) if row is not None else None


async def create_entry(
    session: AsyncSession,
    *,
    title: str,
    body: str,
    symbols: list[str] | None = None,
    mood: str = "neutral",
) -> dict[str, Any]:
    clean_title = _normalize_title(title)
    clean_symbols = _normalize_symbols(symbols)
    clean_mood = _validate_mood(mood)
    clean_body = "" if body is None else str(body)

    row = JournalEntry(
        title=clean_title,
        body=clean_body,
        symbols=clean_symbols,
        mood=clean_mood,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def update_entry(
    session: AsyncSession,
    entry_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    symbols: list[str] | None = None,
    mood: str | None = None,
) -> dict[str, Any] | None:
    row = await session.get(JournalEntry, entry_id)
    if row is None:
        return None

    if title is not None:
        row.title = _normalize_title(title)
    if body is not None:
        row.body = str(body)
    if symbols is not None:
        row.symbols = _normalize_symbols(symbols)
    if mood is not None:
        row.mood = _validate_mood(mood)

    await session.commit()
    await session.refresh(row)
    return _serialize(row)


async def delete_entry(session: AsyncSession, entry_id: int) -> bool:
    row = await session.get(JournalEntry, entry_id)
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    return True


async def autocomplete_symbols(
    session: AsyncSession,
    *,
    prefix: str,
    limit: int = 10,
) -> list[str]:
    """Return distinct symbols across all entries that start with `prefix`.

    SQLite cannot natively expand JSON arrays in SQL, and the journal is a
    single-user dataset — at most a few hundred entries — so we load the
    JSON arrays and de-dupe in Python. If we ever measure this as a hot
    path we can fall back to `json_each()`.
    """
    needle = str(prefix or "").strip().upper()
    capped_limit = _clamp_limit(limit)

    stmt = select(JournalEntry.symbols)
    rows = (await session.execute(stmt)).scalars().all()

    seen: set[str] = set()
    out: list[str] = []
    for arr in rows:
        for raw in arr or []:
            token = str(raw).strip().upper()
            if not token:
                continue
            if needle and not token.startswith(needle):
                continue
            if token in seen:
                continue
            seen.add(token)
            out.append(token)
    out.sort()
    return out[:capped_limit]
