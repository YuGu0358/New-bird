from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class PriceAlertRuleCreateRequest(BaseModel):
    symbol: str
    condition_type: str
    target_value: float
    action_type: str
    order_notional_usd: Optional[float] = None
    note: str = ""


class PriceAlertRuleUpdateRequest(BaseModel):
    enabled: bool


class PriceAlertRuleView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    condition_type: str
    condition_summary: str
    target_value: float
    action_type: str
    action_summary: str
    order_notional_usd: Optional[float] = None
    note: str = ""
    enabled: bool
    triggered_at: Optional[datetime] = None
    trigger_price: Optional[float] = None
    trigger_change_percent: Optional[float] = None
    action_result: str = ""
    last_error: str = ""
    created_at: datetime
    updated_at: datetime
