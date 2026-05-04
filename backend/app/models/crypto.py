"""Pydantic schema for /api/crypto/markets."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CryptoMarketRowModel(BaseModel):
    coin_id: str
    symbol: str
    name: str
    rank: int | None = None
    price_usd: float
    market_cap_usd: float | None = None
    volume_24h_usd: float | None = None
    change_24h_pct: float | None = None
    image_url: str | None = None


class CryptoMarketsResponse(BaseModel):
    rows: list[CryptoMarketRowModel]
    total: int
    limit: int
    sort_by: str
    descending: bool
    generated_at: datetime
    as_of: datetime | None = None
