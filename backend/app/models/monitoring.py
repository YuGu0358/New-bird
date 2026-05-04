from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class AssetUniverseItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    asset_class: Optional[str] = None
    status: Optional[str] = None
    tradable: bool = False
    shortable: bool = False
    fractionable: bool = False


class TrendSnapshot(BaseModel):
    symbol: str
    as_of: datetime
    current_price: Optional[float] = None
    previous_day_price: Optional[float] = None
    previous_week_price: Optional[float] = None
    previous_month_price: Optional[float] = None
    day_change_percent: Optional[float] = None
    week_change_percent: Optional[float] = None
    month_change_percent: Optional[float] = None
    day_direction: str = "flat"
    week_direction: str = "flat"
    month_direction: str = "flat"


class CandidatePoolEntry(BaseModel):
    symbol: str
    rank: int
    category: str
    score: float
    reason: str
    trend: TrendSnapshot


class TrackedSymbolView(BaseModel):
    symbol: str
    tags: list[str]
    trend: TrendSnapshot


class MonitoringOverview(BaseModel):
    generated_at: datetime
    universe_asset_count: int
    selected_symbols: list[str]
    candidate_pool: list[CandidatePoolEntry]
    tracked_symbols: list[TrackedSymbolView]


class WatchlistUpdateRequest(BaseModel):
    symbol: str
