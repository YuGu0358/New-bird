"""Investment-journal API models.

Single-language by design: the body is the user's free-form notes in their
own language and we never translate them, so journal endpoints don't take
the `Accept-Language` / `?lang=` plumbing other domains use.

`mood` is restricted to four canonical values to keep the journal usable
as a structured signal source — Pydantic raises 422 on anything else.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


JournalMood = Literal["bullish", "bearish", "neutral", "watching"]


class JournalEntryView(BaseModel):
    id: int
    title: str
    body: str
    symbols: list[str]
    mood: JournalMood
    created_at: datetime
    updated_at: datetime


class JournalEntryCreateRequest(BaseModel):
    title: str
    body: str = ""
    symbols: list[str] = []
    mood: JournalMood = "neutral"


class JournalEntryUpdateRequest(BaseModel):
    """All fields optional — true PATCH semantics. Omitted keys leave the
    persisted value untouched; passing `None` is identical to omitting."""

    title: Optional[str] = None
    body: Optional[str] = None
    symbols: Optional[list[str]] = None
    mood: Optional[JournalMood] = None


class JournalListResponse(BaseModel):
    items: list[JournalEntryView]
    total: int
    limit: int
    offset: int


class JournalAutocompleteResponse(BaseModel):
    symbols: list[str]
