"""Pydantic schema for /api/docs endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class DocListEntry(BaseModel):
    slug: str
    title: str
    path: str
    size_bytes: int
    modified_at: datetime


class DocListResponse(BaseModel):
    items: list[DocListEntry]
    total: int
    root: str
    as_of: datetime


class DocDetailResponse(BaseModel):
    slug: str
    title: str
    path: str
    content: str
    size_bytes: int
    modified_at: datetime
    as_of: datetime
