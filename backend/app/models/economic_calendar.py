"""Pydantic schema for /api/macro/calendar."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class EventView(BaseModel):
    id: str
    date_utc: datetime
    name: str
    country: str
    category: str
    impact: Literal["high", "medium", "low"]
    source: str  # "seed" | future: "tradingeconomics"


class EconomicCalendarResponse(BaseModel):
    items: list[EventView]
    as_of: datetime
