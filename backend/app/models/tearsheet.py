"""Pydantic schema for /api/backtest/{run_id}/tearsheet."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TearsheetResponse(BaseModel):
    run_id: int
    periods_per_year: int
    risk_free_rate: float

    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    calmar: float | None = None
    total_return: float | None = None
    periods: int

    generated_at: datetime
