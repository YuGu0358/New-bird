"""Dataclass schemas for research-flavored agent outputs.

These are distinct from the buy/hold/sell `PersonaResponse` family in
`base.py`. Market researchers and earnings reviewers produce richer,
more structured artefacts (peer comp tables, variance tables, note
drafts) that don't fit a single verdict shape — so we give them their
own immutable dataclasses parsed by `research_analyzer.ResearchAnalyzer`.

All fields are typed and frozen. Collection fields are tuples (not lists)
so an instance is hashable and safe to share across coroutines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Market research — sector / theme report with peer comps
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PeerRow:
    """One row of a peer comparison table.

    Numeric fields are optional because some companies (recent IPOs,
    foreign listings, segment-only data) won't have every multiple.
    """

    symbol: str
    name: Optional[str]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    ev_ebitda: Optional[float]
    ps_ratio: Optional[float]
    revenue_growth_yoy: Optional[float]
    notes: Optional[str]  # 1-line analyst comment


@dataclass(frozen=True)
class PeerComps:
    """Peer comparison table plus aggregate medians and analyst commentary."""

    peers: tuple[PeerRow, ...]
    median_pe: Optional[float]
    median_ev_ebitda: Optional[float]
    commentary: str


@dataclass(frozen=True)
class IdeaShortlistItem:
    """One name pulled forward from the sector scan as a working idea."""

    symbol: str
    thesis: str  # 1-2 sentence rationale
    catalyst: Optional[str]
    risk: Optional[str]


@dataclass(frozen=True)
class MarketResearchReport:
    """Full output of the market-researcher persona."""

    sector: str
    theme: Optional[str]
    industry_overview: str  # 3-5 paragraphs
    key_drivers: tuple[str, ...]
    competitive_landscape: str
    peer_comps: PeerComps
    ideas_shortlist: tuple[IdeaShortlistItem, ...]
    key_risks: tuple[str, ...]
    sector_thesis: str  # the analyst's bottom line


# ---------------------------------------------------------------------------
# Earnings review — post-print update on a single name
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VarianceRow:
    """One row of an actual-vs-consensus-vs-prior earnings variance table."""

    metric: str  # e.g. "Revenue", "EPS", "Gross Margin"
    actual: Optional[float]
    consensus: Optional[float]
    prior: Optional[float]
    surprise_pct: Optional[float]
    commentary: Optional[str]


@dataclass(frozen=True)
class GuidanceChange:
    """Change in management's forward guidance, line by line."""

    metric: str
    prior_guidance: Optional[str]
    new_guidance: Optional[str]
    direction: str  # "raised" | "lowered" | "maintained" | "introduced"


@dataclass(frozen=True)
class FilingHighlight:
    """A specific quoted excerpt from an SEC filing the analyst flagged."""

    accession_number: Optional[str]
    form_type: str
    excerpt: str  # 1-3 sentence excerpt
    relevance: str  # why analyst should care


@dataclass(frozen=True)
class EarningsReview:
    """Full output of the earnings-reviewer persona."""

    symbol: str
    period: str  # e.g. "FY2025 Q3"
    variance_table: tuple[VarianceRow, ...]
    guidance_changes: tuple[GuidanceChange, ...]
    filing_highlights: tuple[FilingHighlight, ...]
    note_draft: str  # 4-8 paragraph analyst note
    key_takeaways: tuple[str, ...]
    follow_ups: tuple[str, ...]
