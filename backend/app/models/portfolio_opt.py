"""Pydantic schema for /api/portfolio/optimize."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


ModeLiteral = Literal["max_sharpe", "min_volatility", "efficient_return", "hrp"]
BackendLiteral = Literal["pyportfolioopt", "skfolio"]


class PortfolioOptimizeRequest(BaseModel):
    tickers: list[str] = Field(min_length=2)
    lookback_days: int = Field(default=252, ge=21, le=2520)
    mode: ModeLiteral = "max_sharpe"
    target_return: Optional[float] = None
    risk_free_rate: float = Field(default=0.04, ge=0.0, le=0.5)
    # Optional: switch from PyPortfolioOpt (default) to skfolio (HRP, robust covariance, …)
    backend: BackendLiteral = "pyportfolioopt"


class PortfolioOptimizeResponse(BaseModel):
    tickers: list[str]
    lookback_days: int
    mode: str
    target_return: Optional[float] = None
    risk_free_rate: float
    weights: dict[str, float]
    expected_return: float
    expected_volatility: float
    sharpe_ratio: float
    backend: str = "pyportfolioopt"
    as_of: datetime
