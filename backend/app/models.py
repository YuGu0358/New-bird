from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

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


class NewsArticle(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timestamp: datetime
    summary: str
    source: str


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


class ControlResponse(BaseModel):
    success: bool
    message: str


class ResearchSource(BaseModel):
    url: str
    title: str
    source: Optional[str] = None
    domain: Optional[str] = None
    published_date: Optional[str] = None
    score: float = 0.0


class StockResearchReport(BaseModel):
    symbol: str
    company_name: str
    summary: str
    current_performance: str
    key_insights: list[str]
    recommendation: str
    risk_assessment: str
    price_outlook: str
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    sources: list[ResearchSource]
    generated_at: datetime
    research_model: str


class AssetUniverseItem(BaseModel):
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    asset_class: Optional[str] = None
    status: Optional[str] = None
    tradable: bool = False
    shortable: bool = False
    fractionable: bool = False


class TrendSnapshot(BaseModel):
    symbol: str
    as_of: datetime
    current_price: Optional[float] = None
    previous_day_price: Optional[float] = None
    previous_week_price: Optional[float] = None
    previous_month_price: Optional[float] = None
    day_change_percent: Optional[float] = None
    week_change_percent: Optional[float] = None
    month_change_percent: Optional[float] = None
    day_direction: str = "flat"
    week_direction: str = "flat"
    month_direction: str = "flat"


class CandidatePoolEntry(BaseModel):
    symbol: str
    rank: int
    category: str
    score: float
    reason: str
    trend: TrendSnapshot


class TrackedSymbolView(BaseModel):
    symbol: str
    tags: list[str]
    trend: TrendSnapshot


class MonitoringOverview(BaseModel):
    generated_at: datetime
    universe_asset_count: int
    selected_symbols: list[str]
    candidate_pool: list[CandidatePoolEntry]
    tracked_symbols: list[TrackedSymbolView]


class WatchlistUpdateRequest(BaseModel):
    symbol: str


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


class RuntimeSettingItem(BaseModel):
    key: str
    label: str
    category: str
    required: bool
    sensitive: bool
    configured: bool
    source: str
    value: Optional[str] = None
    description: str = ""


class RuntimeSettingsStatus(BaseModel):
    is_ready: bool
    admin_token_required: bool
    missing_required_keys: list[str]
    items: list[RuntimeSettingItem]
    updated_keys: list[str] = []


class SettingsUpdateRequest(BaseModel):
    admin_token: Optional[str] = None
    settings: dict[str, Any]
