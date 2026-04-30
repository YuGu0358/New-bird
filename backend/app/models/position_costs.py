"""Pydantic models for the position_costs surface."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PositionCostView(BaseModel):
    """Wire shape returned by GET / list / upsert endpoints."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    broker_account_id: int
    ticker: str
    avg_cost_basis: float
    total_shares: float
    custom_stop_loss: Optional[float] = None
    custom_take_profit: Optional[float] = None
    notes: str = ""
    created_at: datetime
    updated_at: datetime


class PositionCostListResponse(BaseModel):
    items: list[PositionCostView]


class PositionCostUpsertRequest(BaseModel):
    """Manual override / set-once form. Use /buy for incremental buys."""

    broker_account_id: int = Field(..., gt=0)
    ticker: str = Field(..., min_length=1, max_length=16)
    avg_cost_basis: float = Field(..., ge=0)
    total_shares: float = Field(..., ge=0)
    custom_stop_loss: Optional[float] = Field(None, ge=0)
    custom_take_profit: Optional[float] = Field(None, ge=0)
    notes: str = ""


class PositionCostBuyRequest(BaseModel):
    """Record a new buy fill; service recomputes avg_cost."""

    broker_account_id: int = Field(..., gt=0)
    ticker: str = Field(..., min_length=1, max_length=16)
    fill_price: float = Field(..., gt=0)
    fill_qty: float = Field(..., gt=0)
