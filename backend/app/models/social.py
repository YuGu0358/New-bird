from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SocialProviderStatus(BaseModel):
    name: str
    supported: bool
    configured: bool
    note: Optional[str] = None


class SocialPostAuthor(BaseModel):
    id: str
    username: Optional[str] = None
    display_name: Optional[str] = None
    verified: bool = False
    followers_count: Optional[int] = None


class SocialPostMetrics(BaseModel):
    like_count: int = 0
    repost_count: int = 0
    reply_count: int = 0
    quote_count: int = 0


class SocialCountBucket(BaseModel):
    start: datetime
    end: datetime
    post_count: int


class SocialPostItem(BaseModel):
    provider: str
    post_id: str
    text: str
    created_at: datetime
    url: str
    lang: Optional[str] = None
    author: SocialPostAuthor
    metrics: SocialPostMetrics
    score: float
    matched_terms: list[str] = []


class SocialSearchResponse(BaseModel):
    provider: str
    query: str
    normalized_query: str
    generated_at: datetime
    limit: int
    lang: Optional[str] = None
    exclude_reposts: bool = True
    exclude_replies: bool = True
    min_like_count: int = 0
    min_repost_count: int = 0
    exclude_terms: list[str] = []
    summary: Optional[str] = None
    returned_results: int
    total_results: int
    counts: list[SocialCountBucket]
    posts: list[SocialPostItem]
    rate_limit_remaining: Optional[int] = None
    rate_limit_reset: Optional[int] = None


class SocialSignalQueryProfile(BaseModel):
    symbol: str
    company_name: str
    keywords: list[str] = Field(default_factory=list)
    context_terms: list[str] = Field(default_factory=list)
    x_query: str
    tavily_query: str
    lang: str = "en"
    hours: int = 6


class SocialSignalSource(BaseModel):
    title: str
    url: str
    content: str = ""
    source: Optional[str] = None
    domain: Optional[str] = None
    published_date: Optional[str] = None
    score: float = 0.0


class SocialSignalSnapshotView(BaseModel):
    symbol: str
    generated_at: datetime
    query_profile: SocialSignalQueryProfile
    social_score: float
    market_score: float
    final_weight: float
    action: str
    confidence: float
    confidence_label: str = "low"
    reasons: list[str] = Field(default_factory=list)
    top_posts: list[SocialPostItem] = Field(default_factory=list)
    top_sources: list[SocialSignalSource] = Field(default_factory=list)
    executed: bool = False
    executed_order_id: Optional[str] = None
    execution_message: str = ""


class SocialSignalRunRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    include_watchlist: bool = True
    include_positions: bool = True
    include_candidates: bool = True
    hours: int = 6
    lang: str = "en"
    execute: bool = False
    force_refresh: bool = False


class SocialSignalRunResponse(BaseModel):
    generated_at: datetime
    symbols: list[SocialSignalSnapshotView] = Field(default_factory=list)
    executed_count: int = 0
