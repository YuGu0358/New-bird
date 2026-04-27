"""Observability API models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    timestamp: datetime
    version: str = "1.0.0"


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ReadinessResponse(BaseModel):
    ready: bool
    checks: list[ReadinessCheck] = Field(default_factory=list)


class StrategyHealthResponse(BaseModel):
    active_strategy_name: Optional[str] = None
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    wins_today: int = 0
    losses_today: int = 0
    last_trade_at: Optional[datetime] = None
    streak_kind: str = "none"
    streak_length: int = 0
    open_position_count: int = 0
