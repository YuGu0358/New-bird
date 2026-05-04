"""Pydantic schema for /api/portfolio/overrides."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


TierLiteral = Literal["TIER_1", "TIER_2", "TIER_3"]


class PositionOverrideView(BaseModel):
    id: int
    broker_account_id: int
    ticker: str
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    tier_override: Optional[TierLiteral] = None
    created_at: datetime
    updated_at: datetime


class PositionOverrideListResponse(BaseModel):
    items: list[PositionOverrideView]


class PositionOverrideUpsertRequest(BaseModel):
    broker_account_id: int = Field(gt=0)
    ticker: str = Field(min_length=1)
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    notes: Optional[str] = None
    tier_override: Optional[TierLiteral] = None
