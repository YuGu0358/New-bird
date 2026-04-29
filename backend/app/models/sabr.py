"""Pydantic schema for /api/quantlib/sabr endpoints."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SABRFitRequest(BaseModel):
    forward: float = Field(gt=0)
    expiry_yrs: float = Field(gt=0)
    strikes: list[float]
    market_vols: list[float]
    beta: float = Field(default=0.5, ge=0.0, le=1.0)


class SABRFitResponse(BaseModel):
    forward: float
    expiry_yrs: float
    beta: float
    alpha: float
    rho: float
    nu: float
    strikes: list[float]
    market_vols: list[float]
    model_vols: list[float]
    residuals: list[float]
    generated_at: datetime
