"""Pydantic schema for /api/onchain endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class OnChainObservationModel(BaseModel):
    timestamp: datetime
    value: float | None = None


class OnChainMetricResponse(BaseModel):
    asset: str
    metric_path: str
    since: int | None = None
    until: int | None = None
    interval: str | None = None
    observations: list[OnChainObservationModel]
    generated_at: datetime
    as_of: datetime | None = None
