"""Pydantic schema for /api/portfolio/snapshots."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PositionSnapshotView(BaseModel):
    id: int
    broker_account_id: int
    symbol: str
    snapshot_at: datetime
    qty: float
    avg_cost: Optional[float] = None
    market_value: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pl: Optional[float] = None
    side: str


class PositionSnapshotListResponse(BaseModel):
    items: list[PositionSnapshotView]
