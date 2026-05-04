"""Alpha Arena API models — leaderboard for AI Council personas.

The Arena turns the council from advisory into measurable by running all
personas on the same symbols and scoring their historical buy-verdicts
against current prices.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.agents import ActionPlanView


class ArenaRunRequest(BaseModel):
    """Request body for POST /api/arena/run."""

    symbols: list[str] = Field(..., min_length=1, max_length=5)
    persona_ids: Optional[list[str]] = None


class ArenaCurrentVerdict(BaseModel):
    """One persona's verdict on one symbol, just produced."""

    symbol: str
    persona_id: str
    persona_name: Optional[str] = None
    verdict: str
    confidence: float = 0.0
    reasoning_summary: Optional[str] = None
    action_plan: Optional[ActionPlanView] = None
    created_at: Optional[datetime] = None


class ArenaCallSnapshot(BaseModel):
    """Best/worst historical buy call for a persona — for the scoreboard tile."""

    symbol: Optional[str] = None
    pnl_pct: Optional[float] = None
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    created_at: Optional[datetime] = None


class ArenaScoreboardEntry(BaseModel):
    """Track-record summary for one persona, computed from agent_analyses."""

    persona_id: str
    name: Optional[str] = None
    style: Optional[str] = None
    buy_calls: int = 0
    sell_calls: int = 0
    hold_calls: int = 0
    hits: int = 0
    hit_rate_pct: Optional[float] = None
    avg_buy_pnl_pct: Optional[float] = None
    best_call: Optional[ArenaCallSnapshot] = None
    worst_call: Optional[ArenaCallSnapshot] = None


class ArenaRunResponse(BaseModel):
    """Response for POST /api/arena/run."""

    current: list[ArenaCurrentVerdict] = Field(default_factory=list)
    scoreboard: list[ArenaScoreboardEntry] = Field(default_factory=list)


class ArenaScoreboardResponse(BaseModel):
    """Response for GET /api/arena/scoreboard."""

    scoreboard: list[ArenaScoreboardEntry] = Field(default_factory=list)
    lookback_days: int = 90
