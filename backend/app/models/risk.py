"""Risk-layer API models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RiskPolicyConfigView(BaseModel):
    enabled: bool
    max_position_size_usd: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_daily_loss_usd: Optional[float] = None
    blocklist: list[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = None


class RiskPolicyConfigUpdateRequest(BaseModel):
    enabled: bool = True
    max_position_size_usd: Optional[float] = None
    max_total_exposure_pct: Optional[float] = None
    max_open_positions: Optional[int] = None
    max_daily_loss_usd: Optional[float] = None
    blocklist: list[str] = Field(default_factory=list)


class RiskEventView(BaseModel):
    id: int
    occurred_at: datetime
    policy_name: str
    decision: str
    reason: str
    symbol: str
    side: str
    notional: Optional[float] = None
    qty: Optional[float] = None


class RiskEventsResponse(BaseModel):
    items: list[RiskEventView]
