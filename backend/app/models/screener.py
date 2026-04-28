"""Pydantic schema for /api/screener."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ScreenerRowModel(BaseModel):
    symbol: str
    sector: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    peg_ratio: Optional[float] = None
    revenue_growth: Optional[float] = None
    momentum_3m: Optional[float] = None
    latest_close: Optional[float] = None


class ScreenerResponse(BaseModel):
    rows: list[ScreenerRowModel]
    total: int
    page: int
    page_size: int
    sort_by: str
    descending: bool
    generated_at: datetime
    as_of: Optional[datetime] = None
