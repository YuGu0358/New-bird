"""Pydantic schema for the macro indicator dashboard."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel


class MacroSparkPoint(BaseModel):
    as_of: str
    value: float


class MacroIndicatorView(BaseModel):
    code: str
    category: str
    source: Literal["FRED", "DERIVED"]
    is_ensemble_core: bool
    i18n_key: str
    description_key: str
    unit: str
    default_thresholds: dict[str, Any]
    value: Optional[float] = None
    as_of: Optional[str] = None
    change_abs: Optional[float] = None
    signal: Literal["ok", "warn", "danger", "neutral"]
    sparkline: list[MacroSparkPoint] = []


class MacroEnsembleSummary(BaseModel):
    total_core: int
    signals: dict[str, int]


class MacroDashboardResponse(BaseModel):
    generated_at: datetime
    indicators: list[MacroIndicatorView]
    ensemble: MacroEnsembleSummary
