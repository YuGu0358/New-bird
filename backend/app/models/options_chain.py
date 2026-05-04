"""Pydantic schema for /api/options-chain endpoints."""
from __future__ import annotations

from datetime import date, datetime
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


class FridayScanWall(BaseModel):
    strike: Optional[float] = None
    oi: int
    concentration_pct: Optional[float] = None
    salience_mult: Optional[float] = None
    pressure_pct: Optional[float] = None
    distance_pct: Optional[float] = None
    gex_dollar: float


class FridayScanResponse(BaseModel):
    ticker: str
    spot: float
    target_expiry: str
    dte_calendar: int
    has_data: bool
    atm_iv: Optional[float] = None
    expected_move: Optional[float] = None
    expected_low: Optional[float] = None
    expected_high: Optional[float] = None
    contract_count: int
    total_chain_oi: int
    median_strike_oi: int
    total_friday_gex: float
    friday_gex_pressure_pct: Optional[float] = None
    adv_dollar: Optional[float] = None
    call_wall: FridayScanWall
    put_wall: FridayScanWall
    max_pain: Optional[float] = None
    put_call_oi_ratio: Optional[float] = None
    pinning_score: int
    verdict: str  # BET | MIXED | SKIP
    reasons: list[str]
    suggested_short_call: Optional[float] = None
    suggested_short_put: Optional[float] = None
    breakeven_low: Optional[float] = None
    breakeven_high: Optional[float] = None
    generated_at: datetime


class WallClusterStrikeRow(BaseModel):
    strike: float
    oi: int
    oi_pct_of_peak: float
    distance_pct: Optional[float] = None


class WallClusterBucketRow(BaseModel):
    label: str
    dte_min: int
    dte_max: Optional[int] = None
    contract_count: int
    peak_call_oi: int
    peak_put_oi: int
    top_calls: list[WallClusterStrikeRow]
    top_puts: list[WallClusterStrikeRow]


class WallClustersResponse(BaseModel):
    ticker: str
    spot: float
    threshold_pct: float
    top_n: int
    buckets: list[WallClusterBucketRow]
    generated_at: datetime


class SqueezeScoreResponse(BaseModel):
    ticker: str
    score: int
    level: str  # "low" | "med" | "high"
    signals: list[str]
    factor_scores: dict[str, float]
    max_possible: int
    iv_rank: Optional[float] = None
    short_interest_frac: Optional[float] = None
    generated_at: datetime


class StructureReadResponse(BaseModel):
    ticker: str
    pattern: str
    winning_player: str
    confidence: int
    signals_fired: list[str]
    rationale: list[str]
    inputs_used: dict[str, Optional[float]]
    generated_at: datetime


class OIFloatResponse(BaseModel):
    ticker: str
    spot: float
    float_shares: Optional[int] = None
    total_call_oi: int
    total_put_oi: int
    notional_call_shares: int
    notional_put_shares: int
    notional_total_shares: int
    notional_call_pct: Optional[float] = None
    notional_put_pct: Optional[float] = None
    notional_total_pct: Optional[float] = None
    delta_adjusted_call_shares: float
    delta_adjusted_put_shares: float
    delta_adjusted_total_shares: float
    delta_adjusted_call_pct: Optional[float] = None
    delta_adjusted_put_pct: Optional[float] = None
    delta_adjusted_total_pct: Optional[float] = None
    contracts_with_delta: int
    contracts_total: int
    generated_at: datetime


class IVSurfacePointModel(BaseModel):
    strike: float
    iv: float
    moneyness: float
    open_interest: int
    has_call: bool
    has_put: bool


class IVSurfaceExpiryModel(BaseModel):
    expiry: date
    dte: int
    atm_iv: Optional[float] = None
    skew_pct: Optional[float] = None
    points: list[IVSurfacePointModel]


class IVSurfaceResponse(BaseModel):
    ticker: str
    spot: float
    expiries: list[IVSurfaceExpiryModel]
    strikes: list[float]
    as_of: date
    generated_at: datetime
