"""Pydantic schema for /api/heatmap endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class HeatmapTile(BaseModel):
    symbol: str
    sector: str
    market_cap: Optional[float] = None
    change_1d_pct: Optional[float] = None
    latest_close: Optional[float] = None


class HeatmapSymbolsResponse(BaseModel):
    items: list[HeatmapTile]
    generated_at: datetime
    as_of: Optional[datetime] = None


class HeatmapSectorRow(BaseModel):
    sector: str
    total_market_cap: Optional[float] = None
    change_1d_pct: Optional[float] = None
    constituent_count: int


class HeatmapSectorsResponse(BaseModel):
    items: list[HeatmapSectorRow]
    generated_at: datetime
    as_of: Optional[datetime] = None
