"""Pydantic request/response models for the Factor Forge router."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class FactorRecordView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    formula: str
    fitness: float
    ic_1d: float | None = None
    ic_5d: float | None = None
    ic_20d: float | None = None
    icir: float | None = None
    sharpe: float | None = None
    max_drawdown: float | None = None
    turnover: float | None = None
    generation: int = 0
    created_at: datetime


class FactorLibraryResponse(BaseModel):
    items: list[FactorRecordView]


class ActiveUniverseItem(BaseModel):
    rank: int
    symbol: str
    activity_score: float
    dollar_volume: float


class ActiveUniverseResponse(BaseModel):
    date: date
    items: list[ActiveUniverseItem]


class FactorEvolutionRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    completed_at: datetime | None = None
    status: str
    stage1_best: float | None = None
    stage2_best: float | None = None
    total_persisted: int = 0
    error: str | None = None


class FactorEvolutionRunsResponse(BaseModel):
    items: list[FactorEvolutionRunView]


class RunEvolutionResponse(BaseModel):
    run_id: int
    status: str
