"""User strategy code API models."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class UserStrategyView(BaseModel):
    id: int
    slot_name: str
    display_name: str
    description: str
    status: str
    last_error: str = ""
    created_at: datetime
    updated_at: datetime


class UserStrategyDetail(UserStrategyView):
    source_code: str = ""


class UserStrategyListResponse(BaseModel):
    items: list[UserStrategyView]


class UserStrategyUploadRequest(BaseModel):
    slot_name: str = Field(..., min_length=1, max_length=64,
                            description="Stable id used by @register_strategy and selectors. "
                                        "Convention: prefix with 'user_'.")
    display_name: str = Field("", max_length=96)
    description: str = ""
    source_code: str = Field(..., min_length=1, max_length=100_000)
