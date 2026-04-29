"""Pydantic schema for /api/indicators endpoint."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class IndicatorResponse(BaseModel):
    symbol: str
    range: str
    interval: str
    indicator: str
    params: dict[str, Any]
    timestamps: list[datetime]
    # series keys depend on the indicator: {"value"} for SMA/EMA/RSI,
    # {"macd","signal","histogram"} for MACD, {"upper","middle","lower"}
    # for BBANDS. Each value list is the same length as timestamps.
    series: dict[str, list[float | None]]
    generated_at: datetime
