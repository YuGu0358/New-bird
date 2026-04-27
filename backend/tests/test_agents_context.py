"""AnalysisContext value object + ContextBuilder ABC."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from core.agents.context import (
    AnalysisContext,
    ContextBuilder,
    NewsItem,
    PriceSnapshot,
    PositionSnapshot,
    SocialSignalSnapshot,
)


def test_analysis_context_to_json_block_contains_all_sections() -> None:
    ctx = AnalysisContext(
        symbol="NVDA",
        question="Should I add to my position?",
        price=PriceSnapshot(
            last=850.0, previous_close=820.0, change_pct=3.66,
            week_change_pct=5.2, month_change_pct=18.0, year_change_pct=180.0,
        ),
        fundamentals={"company_name": "NVIDIA", "sector": "Technology", "summary": "GPU leader"},
        recent_news=[
            NewsItem(title="NVDA beats earnings", summary="...", source="Tavily", at=datetime.now(timezone.utc)),
        ],
        social=SocialSignalSnapshot(
            social_score=0.71, market_score=0.55, final_weight=0.66,
            action="buy", confidence_label="high", reasons=["X buzz", "earnings beat"],
        ),
        position=PositionSnapshot(qty=10.0, avg_entry_price=800.0, market_value=8500.0, unrealized_pl=500.0),
        generated_at=datetime.now(timezone.utc),
    )
    block = ctx.to_json_block()
    parsed = json.loads(block)
    assert parsed["symbol"] == "NVDA"
    assert parsed["price"]["last"] == 850.0
    assert parsed["fundamentals"]["company_name"] == "NVIDIA"
    assert len(parsed["recent_news"]) == 1
    assert parsed["social"]["action"] == "buy"
    assert parsed["position"]["qty"] == 10.0


def test_analysis_context_handles_no_position() -> None:
    ctx = AnalysisContext(
        symbol="AAPL",
        question=None,
        price=PriceSnapshot(
            last=200.0, previous_close=200.0, change_pct=0.0,
            week_change_pct=0.0, month_change_pct=0.0, year_change_pct=0.0,
        ),
        fundamentals={},
        recent_news=[],
        social=None,
        position=None,
        generated_at=datetime.now(timezone.utc),
    )
    parsed = json.loads(ctx.to_json_block())
    assert parsed["position"] is None
    assert parsed["social"] is None


def test_context_builder_is_abstract() -> None:
    with pytest.raises(TypeError):
        ContextBuilder()  # type: ignore[abstract]
