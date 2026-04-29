"""Pydantic schema for /api/predictions endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PredictionOutcomeModel(BaseModel):
    label: str
    price: float | None = None


class PredictionMarketModel(BaseModel):
    id: str
    question: str
    slug: str | None = None
    category: str | None = None
    end_date: str | None = None
    closed: bool = False
    active: bool = True
    volume_usd: float | None = None
    liquidity_usd: float | None = None
    yes_price: float | None = None
    outcomes: list[PredictionOutcomeModel]


class PredictionMarketsResponse(BaseModel):
    rows: list[PredictionMarketModel]
    total: int
    limit: int
    sort_by: str
    descending: bool
    generated_at: datetime
    as_of: datetime | None = None
