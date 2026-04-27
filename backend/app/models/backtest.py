"""API request/response models for backtest endpoints."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    strategy_name: str = "strategy_b_v1"
    parameters: dict[str, Any] = Field(default_factory=dict)
    universe: list[str] = Field(default_factory=list)
    start_date: date
    end_date: date
    initial_cash: float = 100_000.0
    enable_risk_guard: bool = False


class BacktestSummaryView(BaseModel):
    id: int
    strategy_name: str
    start_date: str
    end_date: str
    initial_cash: float
    final_cash: float
    final_equity: float
    started_at: datetime
    finished_at: datetime
    status: str
    error_message: str = ""
    metrics: dict[str, float] = Field(default_factory=dict)


class BacktestTradeView(BaseModel):
    symbol: str
    side: str
    qty: float
    price: float
    notional: float
    reason: str
    timestamp: datetime


class BacktestRunResponse(BaseModel):
    summary: BacktestSummaryView
    trades: list[BacktestTradeView]


class BacktestEquityPoint(BaseModel):
    timestamp: datetime
    equity: float


class BacktestEquityCurveResponse(BaseModel):
    run_id: int
    points: list[BacktestEquityPoint]


class BacktestRunsListResponse(BaseModel):
    items: list[BacktestSummaryView]
