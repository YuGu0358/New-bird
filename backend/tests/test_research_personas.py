"""Research personas: prompt content, weight sums, stub-LLM round-trip."""
from __future__ import annotations

import json

import pytest

from core.agents.base import Persona, SignalWeights
from core.agents.llm_router import LLMResponse, LLMRouter
from core.agents.research_analyzer import ResearchAnalyzer
from core.agents.research_personas import (
    EARNINGS_REVIEWER_PERSONA,
    MARKET_RESEARCHER_PERSONA,
    RESEARCH_PERSONA_INDEX,
    RESEARCH_PERSONAS,
    get_research_persona,
    list_research_personas,
)


# ---------------------------------------------------------------------------
# Stub LLM router — used for the round-trip assertion
# ---------------------------------------------------------------------------


class _StubLLMRouter(LLMRouter):
    """Returns a pre-baked text payload, ignoring system/user inputs."""

    def __init__(self, payload: str) -> None:
        self.payload = payload
        self.last_system: str = ""
        self.last_user: str = ""

    async def generate(self, *, system, user, model=None) -> LLMResponse:
        self.last_system = system
        self.last_user = user
        return LLMResponse(text=self.payload, model="stub")


# ---------------------------------------------------------------------------
# Hand-crafted valid JSON payloads matching each schema
# ---------------------------------------------------------------------------


def _market_research_payload() -> str:
    return json.dumps({
        "sector": "semiconductors",
        "theme": "AI accelerators",
        "industry_overview": (
            "The semiconductor sector is in a multi-year capex up-cycle. "
            "Demand is led by AI training clusters; supply is constrained "
            "by leading-edge node availability."
        ),
        "key_drivers": [
            "Hyperscaler AI capex",
            "Edge inference rollout",
            "Foundry capacity at TSMC N3/N2",
        ],
        "competitive_landscape": (
            "Three-way oligopoly at the leading edge: TSMC for foundry, "
            "NVIDIA for accelerators, ASML for lithography."
        ),
        "peer_comps": {
            "peers": [
                {
                    "symbol": "NVDA",
                    "name": "NVIDIA",
                    "market_cap": 3_000_000_000_000,
                    "pe_ratio": 45.0,
                    "ev_ebitda": 38.0,
                    "ps_ratio": 25.0,
                    "revenue_growth_yoy": 1.20,
                    "notes": "Leader in training silicon."
                },
                {
                    "symbol": "AMD",
                    "name": "Advanced Micro Devices",
                    "market_cap": 250_000_000_000,
                    "pe_ratio": 38.0,
                    "ev_ebitda": 30.0,
                    "ps_ratio": 9.0,
                    "revenue_growth_yoy": 0.18,
                    "notes": "MI300 ramp."
                },
            ],
            "median_pe": 41.5,
            "median_ev_ebitda": 34.0,
            "commentary": "Multiples reflect a premium for AI exposure."
        },
        "ideas_shortlist": [
            {
                "symbol": "NVDA",
                "thesis": "Best-positioned for AI training capex.",
                "catalyst": "Q4 print + Blackwell ramp",
                "risk": "Customer concentration"
            },
            {
                "symbol": "AVGO",
                "thesis": "Custom silicon ASIC tailwind.",
                "catalyst": None,
                "risk": None
            },
        ],
        "key_risks": [
            "AI capex digestion",
            "Geopolitical export controls",
            "Cyclical inventory correction"
        ],
        "sector_thesis": (
            "Constructive over 12 months despite stretched multiples; "
            "earnings revisions are still trending higher."
        ),
    })


def _earnings_review_payload() -> str:
    return json.dumps({
        "symbol": "NVDA",
        "period": "FY2025 Q3",
        "variance_table": [
            {
                "metric": "Revenue",
                "actual": 35_080_000_000,
                "consensus": 33_200_000_000,
                "prior": 18_120_000_000,
                "surprise_pct": 0.057,
                "commentary": "Driven by Hopper > Blackwell handoff."
            },
            {
                "metric": "EPS",
                "actual": 0.81,
                "consensus": 0.75,
                "prior": 0.40,
                "surprise_pct": 0.08,
                "commentary": None
            },
        ],
        "guidance_changes": [
            {
                "metric": "Q4 revenue",
                "prior_guidance": None,
                "new_guidance": "$37.5B +/- 2%",
                "direction": "introduced"
            },
        ],
        "filing_highlights": [
            {
                "accession_number": "0001045810-25-000123",
                "form_type": "8-K",
                "excerpt": "Blackwell production ramp on schedule.",
                "relevance": "Confirms supply timeline."
            },
        ],
        "note_draft": (
            "NVDA delivered another beat-and-raise. Revenue of $35.08B "
            "exceeded the Street by ~6%, driven by data-center strength. "
            "EPS of $0.81 beat by 8%. Management guided Q4 to $37.5B at "
            "the midpoint, ahead of consensus. Gross margin held above "
            "75%. We raise our model estimates and stay constructive. "
            "Risk remains customer concentration in three hyperscalers. "
            "Maintain bull stance."
        ),
        "key_takeaways": [
            "Beat-and-raise sustained",
            "Blackwell ramp on track",
            "Margins resilient at 75%+",
        ],
        "follow_ups": [
            "Mix shift between Hopper and Blackwell in Q4?",
            "Sovereign AI pipeline detail.",
        ],
    })


# ---------------------------------------------------------------------------
# Persona registry shape
# ---------------------------------------------------------------------------


EXPECTED_RESEARCH_IDS = {"market_researcher", "earnings_reviewer"}


def test_two_research_personas_registered() -> None:
    assert len(RESEARCH_PERSONAS) == 2
    assert {p.id for p in RESEARCH_PERSONAS} == EXPECTED_RESEARCH_IDS


def test_research_personas_have_unique_ids() -> None:
    ids = [p.id for p in RESEARCH_PERSONAS]
    assert len(ids) == len(set(ids)), "duplicate persona ids"


def test_get_research_persona_unknown_raises() -> None:
    with pytest.raises(KeyError):
        get_research_persona("bogus")


def test_research_persona_index_lookup() -> None:
    assert RESEARCH_PERSONA_INDEX["market_researcher"] is MARKET_RESEARCHER_PERSONA
    assert RESEARCH_PERSONA_INDEX["earnings_reviewer"] is EARNINGS_REVIEWER_PERSONA


def test_list_research_personas_returns_copy() -> None:
    listing = list_research_personas()
    assert len(listing) == 2
    listing.append("not a persona")  # type: ignore[arg-type]
    assert len(list_research_personas()) == 2  # original list unchanged


def test_research_personas_are_persona_instances() -> None:
    for persona in RESEARCH_PERSONAS:
        assert isinstance(persona, Persona)
        assert isinstance(persona.weights, SignalWeights)


# ---------------------------------------------------------------------------
# Weight sum invariant — research personas should sum to 1.0 +/- 0.01
# ---------------------------------------------------------------------------


def _weight_sum(weights: SignalWeights) -> float:
    return (
        weights.fundamentals
        + weights.news
        + weights.social
        + weights.technical
        + weights.macro
    )


def test_market_researcher_weights_sum_to_one() -> None:
    assert abs(_weight_sum(MARKET_RESEARCHER_PERSONA.weights) - 1.0) <= 0.01


def test_earnings_reviewer_weights_sum_to_one() -> None:
    assert abs(_weight_sum(EARNINGS_REVIEWER_PERSONA.weights) - 1.0) <= 0.01


def test_earnings_reviewer_tilts_to_fundamentals() -> None:
    # Expressly the highest-weighted channel for an earnings analyst.
    weights = EARNINGS_REVIEWER_PERSONA.weights
    assert weights.fundamentals >= max(
        weights.news, weights.social, weights.technical, weights.macro
    )


# ---------------------------------------------------------------------------
# System prompts must embed the JSON schema field names
# ---------------------------------------------------------------------------


_MARKET_RESEARCHER_REQUIRED_FIELDS = (
    "sector",
    "theme",
    "industry_overview",
    "key_drivers",
    "competitive_landscape",
    "peer_comps",
    "peers",
    "median_pe",
    "median_ev_ebitda",
    "ideas_shortlist",
    "key_risks",
    "sector_thesis",
)


_EARNINGS_REVIEWER_REQUIRED_FIELDS = (
    "symbol",
    "period",
    "variance_table",
    "guidance_changes",
    "filing_highlights",
    "note_draft",
    "key_takeaways",
    "follow_ups",
    "raised",
    "lowered",
    "maintained",
    "introduced",
)


def test_market_researcher_prompt_embeds_schema_fields() -> None:
    prompt = MARKET_RESEARCHER_PERSONA.system_prompt
    for field_name in _MARKET_RESEARCHER_REQUIRED_FIELDS:
        assert field_name in prompt, f"{field_name!r} missing from prompt"


def test_earnings_reviewer_prompt_embeds_schema_fields() -> None:
    prompt = EARNINGS_REVIEWER_PERSONA.system_prompt
    for field_name in _EARNINGS_REVIEWER_REQUIRED_FIELDS:
        assert field_name in prompt, f"{field_name!r} missing from prompt"


def test_prompts_request_json_only() -> None:
    for persona in RESEARCH_PERSONAS:
        prompt = persona.system_prompt
        assert "JSON" in prompt or "json" in prompt
        assert "first character" in prompt.lower()


def test_prompts_treat_filings_as_untrusted() -> None:
    for persona in RESEARCH_PERSONAS:
        prompt = persona.system_prompt
        assert "UNTRUSTED" in prompt, (
            f"{persona.id} prompt should mark filings/news as UNTRUSTED data"
        )


def test_prompts_omit_paid_mcp_brand_names() -> None:
    """Per the plan, references to FactSet/Daloopa/CapIQ/etc. must be removed."""
    forbidden = ("FactSet", "Daloopa", "CapIQ", "Aiera", "Morningstar")
    for persona in RESEARCH_PERSONAS:
        prompt = persona.system_prompt
        for term in forbidden:
            assert term not in prompt, (
                f"{persona.id} prompt should not name {term!r}"
            )


# ---------------------------------------------------------------------------
# Round-trip: stub LLM router output → ResearchAnalyzer → typed dataclass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_market_researcher_round_trip_through_stub_router() -> None:
    payload = _market_research_payload()
    router = _StubLLMRouter(payload)
    analyzer = ResearchAnalyzer()

    response = await router.generate(
        system=MARKET_RESEARCHER_PERSONA.system_prompt,
        user="sector=semiconductors",
    )
    report = analyzer.parse_market_research(response.text)

    assert report.sector == "semiconductors"
    assert report.theme == "AI accelerators"
    assert len(report.peer_comps.peers) == 2
    assert report.peer_comps.peers[0].symbol == "NVDA"
    assert report.peer_comps.median_pe == 41.5
    assert len(report.ideas_shortlist) == 2
    assert report.ideas_shortlist[1].symbol == "AVGO"
    assert report.ideas_shortlist[1].catalyst is None  # null tolerated


@pytest.mark.asyncio
async def test_earnings_reviewer_round_trip_through_stub_router() -> None:
    payload = _earnings_review_payload()
    router = _StubLLMRouter(payload)
    analyzer = ResearchAnalyzer()

    response = await router.generate(
        system=EARNINGS_REVIEWER_PERSONA.system_prompt,
        user="symbol=NVDA",
    )
    review = analyzer.parse_earnings_review(response.text)

    assert review.symbol == "NVDA"
    assert review.period == "FY2025 Q3"
    assert len(review.variance_table) == 2
    assert review.variance_table[0].metric == "Revenue"
    assert review.variance_table[1].commentary is None  # null tolerated
    assert len(review.guidance_changes) == 1
    assert review.guidance_changes[0].direction == "introduced"
    assert len(review.filing_highlights) == 1
    assert review.filing_highlights[0].form_type == "8-K"
    assert "beat-and-raise" in review.note_draft.lower()
