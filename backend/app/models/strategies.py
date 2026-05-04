from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class StrategyExecutionParameters(BaseModel):
    universe_symbols: list[str]
    preferred_sectors: list[str] = Field(default_factory=list)
    excluded_symbols: list[str] = Field(default_factory=list)
    entry_drop_percent: float = 2.0
    add_on_drop_percent: float = 2.0
    initial_buy_notional: float = 1000.0
    add_on_buy_notional: float = 100.0
    max_daily_entries: int = 3
    max_add_ons: int = 3
    take_profit_target: float = 80.0
    stop_loss_percent: float = 12.0
    max_hold_days: int = 30


class StrategyAnalysisRequest(BaseModel):
    description: str


class MarketObservationRequest(BaseModel):
    """Phase B input — list of symbols the LLM should observe before
    proposing a Strategy B parameterization."""

    symbols: list[str] = Field(..., min_length=1, max_length=8)


class QuantBrainFactorAnalysis(BaseModel):
    source_name: str = "pasted-factor.py"
    factor_names: list[str] = Field(default_factory=list)
    input_fields: list[str] = Field(default_factory=list)
    windows: list[int] = Field(default_factory=list)
    buy_conditions: list[str] = Field(default_factory=list)
    sell_conditions: list[str] = Field(default_factory=list)
    sort_direction: str = "unknown"
    signal_summary: str = ""
    unsupported_features: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    safe_static_analysis: bool = True
    raw_code_chars: int = 0


class QuantBrainFactorAnalysisRequest(BaseModel):
    code: str
    description: str = ""
    source_name: str = "pasted-factor.py"


class StrategyAnalysisDraft(BaseModel):
    suggested_name: str
    original_description: str
    source_documents: list[str] = Field(default_factory=list)
    normalized_strategy: str
    improvement_points: list[str]
    risk_warnings: list[str]
    execution_notes: list[str]
    parameters: StrategyExecutionParameters
    used_openai: bool = False
    factor_analysis: Optional[QuantBrainFactorAnalysis] = None


class StrategySaveRequest(BaseModel):
    name: str
    original_description: str
    normalized_strategy: str
    improvement_points: list[str]
    risk_warnings: list[str]
    execution_notes: list[str]
    parameters: StrategyExecutionParameters
    activate: bool = True


class StrategyPreviewRequest(BaseModel):
    normalized_strategy: str = ""
    parameters: StrategyExecutionParameters


class StrategyPreviewCandidate(BaseModel):
    symbol: str
    score: float
    note: str
    day_change_percent: Optional[float] = None
    week_change_percent: Optional[float] = None
    month_change_percent: Optional[float] = None


class StrategyPreviewResponse(BaseModel):
    universe_size: int
    sample_symbols: list[str]
    likely_trade_symbols: list[str]
    likely_trade_candidates: list[StrategyPreviewCandidate]
    preferred_sectors: list[str]
    excluded_symbols: list[str]
    max_new_positions_per_day: int
    max_capital_per_symbol: float
    max_new_capital_per_day: float
    max_total_capital_if_fully_scaled: float
    entry_trigger_summary: str
    add_on_summary: str
    exit_summary: str
    restart_required: bool = True
    normalized_strategy: str = ""


class StoredStrategy(BaseModel):
    id: int
    name: str
    original_description: str
    normalized_strategy: str
    improvement_points: list[str]
    risk_warnings: list[str]
    execution_notes: list[str]
    parameters: StrategyExecutionParameters
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StrategyLibraryResponse(BaseModel):
    max_slots: int
    items: list[StoredStrategy]
    active_strategy_id: Optional[int] = None


class RegisteredStrategyEntry(BaseModel):
    name: str
    description: str
    parameters_schema: dict[str, Any]


class RegisteredStrategiesResponse(BaseModel):
    items: list[RegisteredStrategyEntry]
