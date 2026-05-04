"""Analyzer composes persona + ctx + LLM and parses structured output."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.agents.analyzer import Analyzer, AnalyzerParseError
from core.agents.context import AnalysisContext, PriceSnapshot
from core.agents.llm_router import LLMResponse, LLMRouter, LLMRouterError
from core.agents.personas import get_persona


class _StubLLMRouter(LLMRouter):
    def __init__(self, payload) -> None:
        self.payload = payload
        self.last_system: str = ""
        self.last_user: str = ""

    async def generate(self, *, system: str, user: str, model=None):
        self.last_system = system
        self.last_user = user
        if isinstance(self.payload, Exception):
            raise self.payload
        return LLMResponse(text=self.payload, model="stub")


def _ctx() -> AnalysisContext:
    return AnalysisContext(
        symbol="NVDA",
        question=None,
        price=PriceSnapshot(
            last=850.0, previous_close=820.0,
            change_pct=3.66, week_change_pct=5.2, month_change_pct=18.0, year_change_pct=180.0,
        ),
        fundamentals={"company_name": "NVIDIA"},
        recent_news=[],
        social=None,
        position=None,
        generated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_analyzer_parses_structured_response() -> None:
    payload = json.dumps({
        "verdict": "buy",
        "confidence": 0.7,
        "reasoning_summary": "Earnings momentum.",
        "key_factors": [
            {"signal": "fundamentals", "weight": 0.6, "interpretation": "Beat estimates."},
            {"signal": "social", "weight": 0.4, "interpretation": "Crowd is excited."},
        ],
        "follow_up_questions": ["What is the FCF outlook?"],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    response = await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())
    assert response.persona_id == "buffett"
    assert response.verdict == "buy"
    assert response.confidence == 0.7
    assert len(response.key_factors) == 2
    assert response.key_factors[0].signal == "fundamentals"
    assert response.follow_up_questions == ["What is the FCF outlook?"]


@pytest.mark.asyncio
async def test_analyzer_passes_persona_system_prompt_to_router() -> None:
    payload = json.dumps({
        "verdict": "hold", "confidence": 0.5, "reasoning_summary": "x",
        "key_factors": [], "follow_up_questions": [],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    persona = get_persona("graham")
    await analyzer.run(persona=persona, ctx=_ctx())
    assert "Benjamin Graham" in router.last_system
    assert "NVDA" in router.last_user


@pytest.mark.asyncio
async def test_analyzer_rejects_invalid_verdict() -> None:
    payload = json.dumps({
        "verdict": "BUY_LOTS", "confidence": 0.7, "reasoning_summary": "x",
        "key_factors": [], "follow_up_questions": [],
    })
    router = _StubLLMRouter(payload)
    analyzer = Analyzer(router=router)
    with pytest.raises(AnalyzerParseError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())


@pytest.mark.asyncio
async def test_analyzer_rejects_non_json() -> None:
    router = _StubLLMRouter("not actually json")
    analyzer = Analyzer(router=router)
    with pytest.raises(AnalyzerParseError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())


@pytest.mark.asyncio
async def test_analyzer_propagates_router_error() -> None:
    router = _StubLLMRouter(LLMRouterError("rate limited"))
    analyzer = Analyzer(router=router)
    with pytest.raises(LLMRouterError):
        await analyzer.run(persona=get_persona("buffett"), ctx=_ctx())
