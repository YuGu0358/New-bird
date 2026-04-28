"""Pydantic schemas for the /api/pine-seeds endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PineSeedsStatusResponse(BaseModel):
    workspace: Optional[str] = None
    repo_url: Optional[str] = None
    last_export_at: Optional[datetime] = None
    tickers_emitted: list[str] = []


class PineSeedsExportRequest(BaseModel):
    symbols: Optional[list[str]] = None
    include_macro: bool = True
    publish: bool = False


class PineSeedsExportResponse(BaseModel):
    workspace: str
    tickers_emitted: list[str]
    rows_written: int
    rows_skipped: int
    errors: list[dict[str, str]]
    published: bool
    publish_reason: Optional[str] = None
    generated_at: datetime
