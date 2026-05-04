"""DataHub HTTP response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TopicListItem(BaseModel):
    name: str
    ttl_seconds: float | None = None
    throttle_seconds: float = 0.0
    replay_on_subscribe: bool = False
    has_dedupe_fn: bool = False


class TopicListResponse(BaseModel):
    topics: list[TopicListItem] = Field(default_factory=list)


class LatestEventResponse(BaseModel):
    topic: str
    payload: dict[str, Any]
