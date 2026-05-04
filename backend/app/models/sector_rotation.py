"""Pydantic schema for /api/sectors/rotation."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class SectorRotationRow(BaseModel):
    symbol: str
    sector: str
    latest_close: Optional[float] = None
    latest_date: Optional[date] = None
    returns: dict[str, Optional[float]]
    ranks: dict[str, Optional[int]]
    rank_change_5d_vs_1m: Optional[int] = None


class SectorRotationResponse(BaseModel):
    windows: list[str]
    rows: list[SectorRotationRow]
    as_of: Optional[date] = None
    generated_at: datetime
