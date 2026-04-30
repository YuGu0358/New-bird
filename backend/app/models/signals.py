"""Pydantic shapes for /api/signals."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SignalView(BaseModel):
    kind: str
    direction: str  # "buy" | "sell"
    strength: float
    ts: datetime
    bar_index: int
    interpretation: str


class SignalsResponse(BaseModel):
    symbol: str
    range: str
    interval: str
    signals: list[SignalView]
    generated_at: datetime
