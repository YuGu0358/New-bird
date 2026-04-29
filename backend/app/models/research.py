from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NewsArticle(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    symbol: str
    timestamp: datetime
    summary: str
    source: str


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


class ChartPoint(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class SymbolChartResponse(BaseModel):
    symbol: str
    range: str
    interval: str
    generated_at: datetime
    latest_price: Optional[float] = None
    range_change_percent: Optional[float] = None
    points: list[ChartPoint]


class CompanyProfileResponse(BaseModel):
    symbol: str
    company_name: str
    exchange: Optional[str] = None
    quote_type: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    category: Optional[str] = None
    fund_family: Optional[str] = None
    website: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    full_time_employees: Optional[int] = None
    location: Optional[str] = None
    business_summary: str
    generated_at: datetime


class TavilySearchSource(BaseModel):
    title: str
    url: str
    content: str = ""
    source: Optional[str] = None
    domain: Optional[str] = None
    published_date: Optional[str] = None
    score: float = 0.0


class TavilySearchResponse(BaseModel):
    query: str
    topic: str
    answer: str
    generated_at: datetime
    results: list[TavilySearchSource]


class RawHeadlinesResponse(BaseModel):
    symbol: str
    max_results: int
    count: int
    headlines: list[TavilySearchSource]
    generated_at: datetime
