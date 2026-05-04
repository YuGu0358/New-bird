"""Pydantic shapes for /api/trade-recommendations/{symbol}.

The recommendation is the synthesis of: position cost basis (if any),
recent signal events, and the user's custom stop/take-profit levels.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class TradeStanceView(BaseModel):
    """One actionable stance line. Multiple may be returned (e.g., "stop
    triggered" + "consider re-entry") so callers can render a list."""

    action: str  # "buy" | "sell" | "hold" | "wait" | "stop_triggered" | "tp_triggered"
    confidence: float  # 0.0 - 1.0
    headline: str  # one-line summary
    rationale: list[str]  # ordered bullet points citing concrete numbers


class TradeRecommendationView(BaseModel):
    symbol: str
    current_price: Optional[float] = None
    has_position: bool = False
    avg_cost_basis: Optional[float] = None
    total_shares: Optional[float] = None
    unrealized_pnl_pct: Optional[float] = None
    custom_stop_loss: Optional[float] = None
    custom_take_profit: Optional[float] = None
    recent_signals_count: int = 0
    stances: list[TradeStanceView]
    generated_at: datetime
