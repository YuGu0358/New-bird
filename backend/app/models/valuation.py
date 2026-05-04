"""Pydantic schema for /api/valuation endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class DCFRequest(BaseModel):
    fcfe0: float = Field(..., description="Most-recent FCFE (per share unless shares_out is set)")
    growth_stage1: float = Field(..., description="Decimal growth rate for stage 1 (e.g. 0.10)")
    growth_terminal: float = Field(..., description="Decimal terminal growth rate (e.g. 0.025)")
    discount_rate: float = Field(..., description="Decimal discount rate (e.g. 0.10)")
    years_stage1: int = Field(7, ge=1, le=20)
    shares_out: Optional[float] = None


class DCFGridPoint(BaseModel):
    delta_growth: float
    delta_discount: float
    fair_value: float


class DCFResponse(BaseModel):
    inputs: dict
    fair_value_per_share: float
    fair_low: float
    fair_high: float
    breakdown: dict[str, float]
    grid: list[DCFGridPoint]
    generated_at: datetime


class PEChannelResponse(BaseModel):
    ticker: str
    current_price: Optional[float] = None
    ttm_eps: Optional[float] = None
    current_pe: Optional[float] = None
    pe_p5: Optional[float] = None
    pe_p25: Optional[float] = None
    pe_p50: Optional[float] = None
    pe_p75: Optional[float] = None
    pe_p95: Optional[float] = None
    fair_p5: Optional[float] = None
    fair_p25: Optional[float] = None
    fair_p50: Optional[float] = None
    fair_p75: Optional[float] = None
    fair_p95: Optional[float] = None
    sample_size: int
    generated_at: datetime
