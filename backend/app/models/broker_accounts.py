"""Pydantic schema for /api/broker-accounts."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TierLiteral = Literal["TIER_1", "TIER_2", "TIER_3"]


class BrokerAccountView(BaseModel):
    id: int
    broker: str
    account_id: str
    alias: str
    tier: TierLiteral
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BrokerAccountListResponse(BaseModel):
    items: list[BrokerAccountView]


class BrokerAccountCreateRequest(BaseModel):
    broker: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    alias: str = ""
    tier: TierLiteral = "TIER_2"


class BrokerAccountAliasUpdateRequest(BaseModel):
    alias: str


class BrokerAccountTierUpdateRequest(BaseModel):
    tier: TierLiteral


class BrokerAccountActiveUpdateRequest(BaseModel):
    is_active: bool
