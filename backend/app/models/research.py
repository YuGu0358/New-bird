from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


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


class NewsClusterRow(BaseModel):
    cluster_id: int
    exemplar_title: Optional[str] = None
    size: int
    member_indices: list[int]


class NewsClustersResponse(BaseModel):
    symbol: str
    k_clusters: int
    clusters: list[NewsClusterRow]
    headlines: list[TavilySearchSource]
    generated_at: datetime


class FilingItem(BaseModel):
    accession_number: str
    form_type: str
    filing_date: str
    primary_document: str = ""
    primary_doc_url: str = ""
    items: str = ""
    report_date: str = ""


class SecEdgarFilingsResponse(BaseModel):
    symbol: str
    cik: str
    form_types: list[str]
    limit: int
    filings: list[FilingItem]
    as_of: datetime
    generated_at: datetime
    source: str = "SEC EDGAR"


# ---------------------------------------------------------------------------
# Phase 4 — Research router request/response models.
#
# These mirror the frozen dataclasses in `core.agents.research_schemas` so the
# router can return JSON-friendly Pydantic objects. Tuples become lists.
# ---------------------------------------------------------------------------


class MarketResearchRequest(BaseModel):
    sector: str = Field(..., min_length=1)
    theme: Optional[str] = None
    peer_count: int = Field(10, ge=1, le=20)


class EarningsReviewRequest(BaseModel):
    """No body fields required — symbol comes from the path parameter."""

    pass


class PeerRowResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ps_ratio: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    notes: Optional[str] = None


class PeerCompsResponse(BaseModel):
    peers: list[PeerRowResponse]
    median_pe: Optional[float] = None
    median_ev_ebitda: Optional[float] = None
    commentary: str = ""


class IdeaShortlistItemResponse(BaseModel):
    symbol: str
    thesis: str
    catalyst: Optional[str] = None
    risk: Optional[str] = None


class MarketResearchReportResponse(BaseModel):
    sector: str
    theme: Optional[str] = None
    industry_overview: str
    key_drivers: list[str]
    competitive_landscape: str
    peer_comps: PeerCompsResponse
    ideas_shortlist: list[IdeaShortlistItemResponse]
    key_risks: list[str]
    sector_thesis: str


class VarianceRowResponse(BaseModel):
    metric: str
    actual: Optional[float] = None
    consensus: Optional[float] = None
    prior: Optional[float] = None
    surprise_pct: Optional[float] = None
    commentary: Optional[str] = None


class GuidanceChangeResponse(BaseModel):
    metric: str
    prior_guidance: Optional[str] = None
    new_guidance: Optional[str] = None
    direction: str


class FilingHighlightResponse(BaseModel):
    accession_number: Optional[str] = None
    form_type: str
    excerpt: str
    relevance: str


class EarningsReviewResponse(BaseModel):
    symbol: str
    period: str
    variance_table: list[VarianceRowResponse]
    guidance_changes: list[GuidanceChangeResponse]
    filing_highlights: list[FilingHighlightResponse]
    note_draft: str
    key_takeaways: list[str]
    follow_ups: list[str]


class CompsTableResponse(BaseModel):
    """Deterministic peer comps — no LLM."""

    symbol: str
    peers: list[PeerRowResponse]
    median_pe: Optional[float] = None
    median_ev_ebitda: Optional[float] = None
    commentary: str
    generated_at: datetime


class DcfResponse(BaseModel):
    """Wrapper around `/api/valuation/dcf` output, plus a `source` tag."""

    symbol: str
    inputs: dict[str, Any]
    fair_value_per_share: float
    fair_low: float
    fair_high: float
    breakdown: dict[str, float]
    grid: list[dict[str, Any]]
    generated_at: datetime
    source: str = "internal valuation engine"
