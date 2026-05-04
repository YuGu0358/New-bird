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
    quarantined: bool = False
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


class EvolutionStatusResponse(BaseModel):
    is_running: bool
    current_generation: int
    best_fitness_recent: float | None = None
    last_generation_completed_at: datetime | None = None
    population_size: int
    library_count: int
    error: str | None = None


class EvolutionControlResponse(BaseModel):
    is_running: bool
    message: str


class GenerationStatView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    generation: int
    best_fitness: float | None = None
    median_fitness: float | None = None
    persisted_count: int = 0
    evaluated_count: int = 0
    completed_at: datetime


class GenerationHistoryResponse(BaseModel):
    items: list[GenerationStatView]


class PopulationSlotView(BaseModel):
    slot: int
    formula: str
    fitness: float


class PopulationSnapshotResponse(BaseModel):
    generation: int
    slots: list[PopulationSlotView]


class LandscapePoint(BaseModel):
    id: int
    formula: str
    fitness: float
    ic_5d: float | None = None
    x: float
    y: float


class LandscapeResponse(BaseModel):
    items: list[LandscapePoint]


class ReasoningEntry(BaseModel):
    factor_id: int | None = None
    formula: str | None = None
    fitness: float | None = None
    weight: float | None = None
    interpretation: str | None = None


class RiskSignal(BaseModel):
    kind: str
    value: float | None = None
    message: str


class RecommendationView(BaseModel):
    date: str
    symbol: str
    action: str
    entry_low: float
    entry_high: float
    stop_loss: float
    take_profit: float
    holding_days: int
    position_pct: float
    confidence: float
    ensemble_score: float
    reasoning: list[ReasoningEntry] = []
    risk_signals: list[RiskSignal] = []
    rank: int


class RecommendationsResponse(BaseModel):
    items: list[RecommendationView]
    generated_at: str | None = None
