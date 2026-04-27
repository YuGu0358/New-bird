"""QuantLib API request/response models."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class OptionPriceRequest(BaseModel):
    spot: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    rate: float = Field(..., ge=-0.5, le=1.0)
    dividend: float = Field(0.0, ge=-0.5, le=1.0)
    volatility: float = Field(..., gt=0, le=5.0)
    valuation: date
    expiry: date
    right: Literal["call", "put"] = "call"
    style: Literal["european", "american"] = "european"
    steps: int = Field(200, ge=20, le=2000)


class OptionPriceResponse(BaseModel):
    style: str
    right: str
    price: float
    days_to_expiry: int


class OptionGreeksRequest(BaseModel):
    spot: float = Field(..., gt=0)
    strike: float = Field(..., gt=0)
    rate: float = Field(..., ge=-0.5, le=1.0)
    dividend: float = Field(0.0, ge=-0.5, le=1.0)
    volatility: float = Field(..., gt=0, le=5.0)
    valuation: date
    expiry: date
    right: Literal["call", "put"] = "call"


class OptionGreeksResponse(BaseModel):
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


class BondAnalyticsRequest(BaseModel):
    settlement: date
    maturity: date
    coupon_rate: float = Field(..., ge=0, le=1.0)
    frequency: Literal[1, 2, 4, 12] = 2
    face: float = Field(100.0, gt=0)
    clean_price: float = Field(100.0, gt=0)


class BondYieldResponse(BaseModel):
    yield_to_maturity: float


class BondRiskResponse(BaseModel):
    yield_to_maturity: float
    macaulay_duration: float
    modified_duration: float
    convexity: float


class VaRRequest(BaseModel):
    method: Literal["parametric", "historical"] = "parametric"
    notional: float = Field(..., gt=0)
    confidence: float = Field(0.95, gt=0, lt=1)
    horizon_days: int = Field(1, ge=1, le=365)
    # parametric inputs
    mean_return: float = 0.0
    std_return: float = 0.0
    # historical inputs
    returns: Optional[list[float]] = None


class VaRResponse(BaseModel):
    var: float
    cvar: float
    confidence: float
    horizon_days: int
    method: str
