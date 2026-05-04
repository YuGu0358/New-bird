"""Pydantic models internal to social-signal scoring + package-wide constants.

Distinct from the API response models in app.models.social — these are
implementation-detail shapes used by classifier and scoring code.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel

DEFAULT_SOCIAL_LOOKBACK_HOURS = 6
DEFAULT_SOCIAL_POST_LIMIT = 30
DEFAULT_SOCIAL_LANG = "en"
DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES = 15
SOCIAL_SIGNAL_COOLDOWN = timedelta(minutes=60)
MAX_SOCIAL_EXECUTIONS_PER_DAY = 3
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 30
MARKET_CLOSE_HOUR = 16


class SocialSignalQueryProfile(BaseModel):
    symbol: str
    company_name: str
    keywords: list[str]
    context_terms: list[str]
    x_query: str
    tavily_query: str
    lang: str = DEFAULT_SOCIAL_LANG
    hours: int = DEFAULT_SOCIAL_LOOKBACK_HOURS


class SocialTextClassification(BaseModel):
    label: Literal["bullish", "bearish", "neutral", "irrelevant"]
    confidence: float
    rationale: str = ""
    mention_entity: bool = True


class _OpenAIClassificationResponse(BaseModel):
    label: Literal["bullish", "bearish", "neutral", "irrelevant"]
    confidence: float
    rationale: str
    mention_entity: bool
