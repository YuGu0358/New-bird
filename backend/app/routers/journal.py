"""Investment-journal CRUD + symbol autocomplete endpoints.

Single-language by design: bodies are stored as the user wrote them, so we
do NOT inject `RequestLang` here. All validation lives in
`journal_service`; this layer just translates `ValueError` -> 400 and
"missing entry" -> 404.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    JournalAutocompleteResponse,
    JournalEntryCreateRequest,
    JournalEntryUpdateRequest,
    JournalEntryView,
    JournalListResponse,
)
from app.services import journal_service

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("", response_model=JournalListResponse)
async def list_journal_entries(
    session: SessionDep,
    symbol: Optional[str] = None,
    mood: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> JournalListResponse:
    try:
        items = await journal_service.list_entries(
            session,
            symbol=symbol,
            mood=mood,
            search=search,
            limit=limit,
            offset=offset,
        )
        total = await journal_service.count_entries(
            session, symbol=symbol, mood=mood, search=search
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return JournalListResponse(
        items=[JournalEntryView(**row) for row in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=JournalEntryView)
async def create_journal_entry(
    request: JournalEntryCreateRequest,
    session: SessionDep,
) -> JournalEntryView:
    try:
        row = await journal_service.create_entry(
            session,
            title=request.title,
            body=request.body,
            symbols=request.symbols,
            mood=request.mood,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return JournalEntryView(**row)


# IMPORTANT: static path before the dynamic `/{entry_id}` so FastAPI does
# NOT match `symbols` as an entry_id.
@router.get("/symbols/autocomplete", response_model=JournalAutocompleteResponse)
async def autocomplete_journal_symbols(
    session: SessionDep,
    prefix: str = "",
    limit: int = 10,
) -> JournalAutocompleteResponse:
    try:
        symbols = await journal_service.autocomplete_symbols(
            session, prefix=prefix, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return JournalAutocompleteResponse(symbols=symbols)


@router.get("/{entry_id}", response_model=JournalEntryView)
async def get_journal_entry(
    entry_id: int,
    session: SessionDep,
) -> JournalEntryView:
    try:
        row = await journal_service.get_entry(session, entry_id)
    except Exception as exc:
        raise service_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return JournalEntryView(**row)


@router.patch("/{entry_id}", response_model=JournalEntryView)
async def update_journal_entry(
    entry_id: int,
    request: JournalEntryUpdateRequest,
    session: SessionDep,
) -> JournalEntryView:
    try:
        row = await journal_service.update_entry(
            session,
            entry_id,
            title=request.title,
            body=request.body,
            symbols=request.symbols,
            mood=request.mood,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return JournalEntryView(**row)


@router.delete("/{entry_id}", response_model=dict[str, bool])
async def delete_journal_entry(
    entry_id: int,
    session: SessionDep,
) -> dict[str, bool]:
    try:
        removed = await journal_service.delete_entry(session, entry_id)
    except Exception as exc:
        raise service_error(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return {"removed": removed}
