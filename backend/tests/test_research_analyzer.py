"""ResearchAnalyzer: JSON parsing, fence stripping, schema mismatch errors."""
from __future__ import annotations

import json

import pytest

from core.agents.research_analyzer import (
    ResearchAnalyzer,
    ResearchAnalyzerParseError,
)
from core.agents.research_schemas import (
    EarningsReview,
    MarketResearchReport,
)


# ---------------------------------------------------------------------------
# Fixture helpers — minimal valid payloads
# ---------------------------------------------------------------------------


def _minimal_market_research_dict() -> dict:
    return {
        "sector": "energy",
        "theme": None,
        "industry_overview": "Cycle-low oil services capex.",
        "key_drivers": ["Brent above $80", "Permian rig adds"],
        "competitive_landscape": "Three integrated majors plus a long tail.",
        "peer_comps": {
            "peers": [
                {
                    "symbol": "XOM",
                    "name": "Exxon Mobil",
                    "market_cap": 500_000_000_000,
                    "pe_ratio": 12.0,
                    "ev_ebitda": 6.0,
                    "ps_ratio": 1.2,
                    "revenue_growth_yoy": 0.05,
                    "notes": "Permian-heavy"
                },
            ],
            "median_pe": 12.0,
            "median_ev_ebitda": 6.0,
            "commentary": "Multiples compressed."
        },
        "ideas_shortlist": [
            {
                "symbol": "XOM",
                "thesis": "Free cash flow inflection.",
                "catalyst": None,
                "risk": None
            },
        ],
        "key_risks": ["Demand destruction", "Regulatory carbon costs"],
        "sector_thesis": "Constructive on duration of upcycle.",
    }


def _minimal_earnings_review_dict() -> dict:
    return {
        "symbol": "AAPL",
        "period": "FY2025 Q4",
        "variance_table": [
            {
                "metric": "Revenue",
                "actual": 94_000_000_000,
                "consensus": 93_000_000_000,
                "prior": 89_000_000_000,
                "surprise_pct": 0.011,
                "commentary": None
            },
        ],
        "guidance_changes": [],
        "filing_highlights": [
            {
                "accession_number": None,
                "form_type": "8-K",
                "excerpt": "Services revenue at all-time high.",
                "relevance": "Mix-shift continues."
            },
        ],
        "note_draft": "Solid print, modest beat. Services momentum intact.",
        "key_takeaways": ["Beat", "Services strong"],
        "follow_ups": ["iPhone unit detail"],
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_parses_well_formed_market_research_json() -> None:
    raw = json.dumps(_minimal_market_research_dict())
    report = ResearchAnalyzer().parse_market_research(raw)
    assert isinstance(report, MarketResearchReport)
    assert report.sector == "energy"
    assert report.theme is None  # null in optional field
    assert report.peer_comps.peers[0].symbol == "XOM"
    assert report.ideas_shortlist[0].catalyst is None


def test_parses_well_formed_earnings_review_json() -> None:
    raw = json.dumps(_minimal_earnings_review_dict())
    review = ResearchAnalyzer().parse_earnings_review(raw)
    assert isinstance(review, EarningsReview)
    assert review.symbol == "AAPL"
    assert review.guidance_changes == ()  # empty list -> empty tuple
    assert review.variance_table[0].commentary is None


# ---------------------------------------------------------------------------
# Markdown fence stripping
# ---------------------------------------------------------------------------


def test_strips_json_markdown_fences_on_market_research() -> None:
    inner = json.dumps(_minimal_market_research_dict())
    raw = f"```json\n{inner}\n```"
    report = ResearchAnalyzer().parse_market_research(raw)
    assert report.sector == "energy"


def test_strips_plain_markdown_fences_on_earnings_review() -> None:
    inner = json.dumps(_minimal_earnings_review_dict())
    raw = f"```\n{inner}\n```"
    review = ResearchAnalyzer().parse_earnings_review(raw)
    assert review.symbol == "AAPL"


def test_strips_uppercase_json_fence() -> None:
    inner = json.dumps(_minimal_market_research_dict())
    raw = f"```JSON\n{inner}\n```"
    report = ResearchAnalyzer().parse_market_research(raw)
    assert report.sector == "energy"


def test_tolerates_leading_and_trailing_whitespace() -> None:
    inner = json.dumps(_minimal_earnings_review_dict())
    raw = f"   \n  ```json\n{inner}\n```  \n"
    review = ResearchAnalyzer().parse_earnings_review(raw)
    assert review.period == "FY2025 Q4"


# ---------------------------------------------------------------------------
# Optional / null tolerance
# ---------------------------------------------------------------------------


def test_market_research_tolerates_nulls_in_optional_peer_fields() -> None:
    payload = _minimal_market_research_dict()
    payload["peer_comps"]["peers"][0]["pe_ratio"] = None
    payload["peer_comps"]["peers"][0]["notes"] = None
    payload["peer_comps"]["median_pe"] = None
    raw = json.dumps(payload)
    report = ResearchAnalyzer().parse_market_research(raw)
    assert report.peer_comps.peers[0].pe_ratio is None
    assert report.peer_comps.peers[0].notes is None
    assert report.peer_comps.median_pe is None


def test_earnings_review_tolerates_nulls_in_optional_variance_fields() -> None:
    payload = _minimal_earnings_review_dict()
    payload["variance_table"][0]["consensus"] = None
    payload["variance_table"][0]["surprise_pct"] = None
    payload["filing_highlights"][0]["accession_number"] = None
    raw = json.dumps(payload)
    review = ResearchAnalyzer().parse_earnings_review(raw)
    assert review.variance_table[0].consensus is None
    assert review.variance_table[0].surprise_pct is None
    assert review.filing_highlights[0].accession_number is None


# ---------------------------------------------------------------------------
# Forward compatibility — extra unknown fields do not break parsing
# ---------------------------------------------------------------------------


def test_market_research_ignores_extra_unknown_fields() -> None:
    payload = _minimal_market_research_dict()
    payload["future_field"] = "ignored"
    payload["peer_comps"]["future_subfield"] = 42
    payload["peer_comps"]["peers"][0]["analyst_rating"] = "buy"
    raw = json.dumps(payload)
    report = ResearchAnalyzer().parse_market_research(raw)
    assert report.sector == "energy"


def test_earnings_review_ignores_extra_unknown_fields() -> None:
    payload = _minimal_earnings_review_dict()
    payload["future_section"] = {"a": 1}
    payload["variance_table"][0]["future_metric_meta"] = "x"
    raw = json.dumps(payload)
    review = ResearchAnalyzer().parse_earnings_review(raw)
    assert review.symbol == "AAPL"


# ---------------------------------------------------------------------------
# Schema mismatch errors
# ---------------------------------------------------------------------------


def test_raises_on_invalid_top_level_json() -> None:
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research("not actually json")


def test_raises_on_array_top_level() -> None:
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research("[1, 2, 3]")


def test_raises_on_empty_response() -> None:
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research("   ")


def test_raises_on_missing_required_market_research_field() -> None:
    payload = _minimal_market_research_dict()
    payload.pop("sector_thesis")
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError) as excinfo:
        ResearchAnalyzer().parse_market_research(raw)
    assert "sector_thesis" in str(excinfo.value)


def test_raises_on_missing_required_earnings_review_field() -> None:
    payload = _minimal_earnings_review_dict()
    payload.pop("note_draft")
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError) as excinfo:
        ResearchAnalyzer().parse_earnings_review(raw)
    assert "note_draft" in str(excinfo.value)


def test_raises_on_missing_peer_row_required_field() -> None:
    payload = _minimal_market_research_dict()
    del payload["peer_comps"]["peers"][0]["symbol"]
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research(raw)


def test_raises_on_invalid_guidance_direction() -> None:
    payload = _minimal_earnings_review_dict()
    payload["guidance_changes"] = [
        {
            "metric": "FY revenue",
            "prior_guidance": "$1B",
            "new_guidance": "$1.1B",
            "direction": "skyrocketed",  # not in enum
        }
    ]
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError) as excinfo:
        ResearchAnalyzer().parse_earnings_review(raw)
    assert "direction" in str(excinfo.value)


def test_raises_on_wrong_type_for_array_field() -> None:
    payload = _minimal_market_research_dict()
    payload["key_drivers"] = "should be an array"
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research(raw)


def test_raises_on_non_string_for_required_string_field() -> None:
    payload = _minimal_earnings_review_dict()
    payload["symbol"] = 42  # required string
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_earnings_review(raw)


def test_raises_on_non_numeric_for_optional_number_field() -> None:
    payload = _minimal_market_research_dict()
    payload["peer_comps"]["peers"][0]["pe_ratio"] = "not a number"
    raw = json.dumps(payload)
    with pytest.raises(ResearchAnalyzerParseError):
        ResearchAnalyzer().parse_market_research(raw)
