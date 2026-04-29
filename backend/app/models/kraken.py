"""Pydantic schema for /api/kraken endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class KrakenTickerResponse(BaseModel):
    pair: str
    result: dict[str, Any]  # Kraken returns nested dict-of-dict
    generated_at: datetime


class KrakenTradesResponse(BaseModel):
    pair: str
    result: dict[str, Any]
    generated_at: datetime
