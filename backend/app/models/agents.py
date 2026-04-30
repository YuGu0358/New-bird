"""AI Council API models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PersonaWeightsView(BaseModel):
    fundamentals: float
    news: float
    social: float
    technical: float
    macro: float


class PersonaView(BaseModel):
    id: str
    name: str
    style: str
    description: str
    weights: PersonaWeightsView


class PersonasResponse(BaseModel):
    items: list[PersonaView]


class AnalysisRequest(BaseModel):
    persona_id: str
    symbol: str
    question: Optional[str] = None
    model: Optional[str] = None


class CouncilRequest(BaseModel):
    persona_ids: list[str] = Field(..., min_length=1)
    symbol: str
    question: Optional[str] = None
    model: Optional[str] = None


class KeyFactorView(BaseModel):
    signal: str
    weight: float
    interpretation: str


class ActionPlanView(BaseModel):
    """Concrete buy/sell timing surfaced to the UI."""

    should_buy_now: Optional[bool] = None
    entry_zone_low: Optional[float] = None
    entry_zone_high: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    time_horizon: Optional[str] = None
    trigger_condition: Optional[str] = None


class AnalysisView(BaseModel):
    id: int
    persona_id: str
    symbol: str
    question: Optional[str] = None
    verdict: str
    confidence: float
    reasoning_summary: str
    key_factors: list[KeyFactorView] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    action_plan: Optional[ActionPlanView] = None
    model: str = ""
    created_at: datetime


class CouncilResponse(BaseModel):
    symbol: str
    analyses: list[AnalysisView]


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisView]
