"""Pydantic schema for /api/options-chain endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class GexStrikeRow(BaseModel):
    strike: float
    call_gex: float
    put_gex: float
    net_gex: float
    call_oi: int
    put_oi: int
    oi: int
    call_volume: int
    put_volume: int


class GexExpiryRow(BaseModel):
    expiry: str
    total_gex: float
    max_pain: Optional[float] = None
    contracts: int


class GexSummaryResponse(BaseModel):
    ticker: str
    spot: float
    call_wall: Optional[float] = None
    put_wall: Optional[float] = None
    zero_gamma: Optional[float] = None
    max_pain: Optional[float] = None
    total_gex: float
    call_gex_total: float
    put_gex_total: float
    by_strike: list[GexStrikeRow]
    by_expiry: list[GexExpiryRow]
    expiries: list[str]
    generated_at: datetime


class ExpiryFocusStrikeRow(BaseModel):
    strike: float
    open_interest: int
    volume: int
    volume_oi_ratio: Optional[float] = None
    iv: Optional[float] = None
    delta: Optional[float] = None
    distance_pct: float


class ExpiryFocusResponse(BaseModel):
    ticker: str
    expiry: str
    dte: int
    spot: float
    atm_iv: Optional[float] = None
    expected_move: Optional[float] = None
    expected_low: Optional[float] = None
    expected_high: Optional[float] = None
    max_pain: Optional[float] = None
    total_call_oi: int
    total_put_oi: int
    put_call_oi_ratio: Optional[float] = None
    top_call_strikes: list[ExpiryFocusStrikeRow]
    top_put_strikes: list[ExpiryFocusStrikeRow]
    generated_at: datetime
