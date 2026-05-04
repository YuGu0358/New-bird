"""Pydantic schema for /api/screener."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ScreenerRowModel(BaseModel):
    symbol: str
    sector: str
    market_cap: float | None = None
    pe_ratio: float | None = None
    peg_ratio: float | None = None
    revenue_growth: float | None = None
    momentum_3m: float | None = None
    latest_close: float | None = None


class ScreenerResponse(BaseModel):
    rows: list[ScreenerRowModel]
    total: int
    page: int
    page_size: int
    sort_by: str
    descending: bool
    generated_at: datetime
    as_of: datetime | None = None
