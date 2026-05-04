from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Account(BaseModel):
    account_id: str
    status: str
    currency: str = "USD"
    cash: float
    buying_power: float
    equity: float
    last_equity: float


class Position(BaseModel):
    symbol: str
    qty: float
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float


class TradeRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    qty: float
    net_profit: float
    exit_reason: str


class OrderRecord(BaseModel):
    order_id: str
    symbol: str
    side: str
    order_type: str
    status: str
    qty: Optional[float] = None
    notional: Optional[float] = None
    filled_avg_price: Optional[float] = None
    created_at: Optional[datetime] = None


class BotStatus(BaseModel):
    is_running: bool
    started_at: Optional[datetime] = None
    uptime_seconds: Optional[int] = None
    last_error: Optional[str] = None
    active_strategy_name: Optional[str] = None


class ControlResponse(BaseModel):
    success: bool
    message: str
