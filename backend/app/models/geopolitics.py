"""Pydantic schema for /api/geopolitics endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class GeopoliticalEvent(BaseModel):
    id: str
    date_utc: datetime
    title: str
    region: str
    category: str
    severity: int  # 0..100
    asset_classes: list[str]
    summary: str
    source: str = "seed"


class GeopoliticalEventsResponse(BaseModel):
    items: list[GeopoliticalEvent]
    as_of: datetime
    total: int
    regions: list[str]      # full canonical region list (for UI dropdowns)
    categories: list[str]   # full canonical category list
