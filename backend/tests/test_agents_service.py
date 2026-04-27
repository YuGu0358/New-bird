"""agents_service.analyze() persists rows + returns dict."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.database import AsyncSessionLocal, AgentAnalysis


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Each test runs against a fresh tmp DB so AgentAnalysis rows don't leak."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "agents.db"
    new_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False, future=True)
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


def _stub_response_json(verdict: str = "buy", confidence: float = 0.7) -> str:
    return json.dumps({
        "verdict": verdict,
        "confidence": confidence,
        "reasoning_summary": "Stubbed reasoning that is non-empty.",
        "key_factors": [
            {"signal": "fundamentals", "weight": 0.6, "interpretation": "Beat estimates."},
        ],
        "follow_up_questions": ["What about competition?"],
    })


async def _stub_build(self, symbol, *, question=None):
    from core.agents.context import AnalysisContext, PriceSnapshot
    return AnalysisContext(
        symbol=symbol.upper(),
        question=question,
        price=PriceSnapshot(
            last=100.0, previous_close=98.0,
            change_pct=2.0, week_change_pct=3.0, month_change_pct=5.0, year_change_pct=10.0,
        ),
        fundamentals={"company_name": symbol},
        recent_news=[],
        social=None,
        position=None,
        generated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_analyze_persists_row_and_returns_dict() -> None:
    from app.services import agents_service

    async def fake_generate(self, *, system, user, model=None):
        from core.agents.llm_router import LLMResponse
        return LLMResponse(text=_stub_response_json("buy", 0.72), model="stub-1")

    with patch("core.agents.OpenAILLMRouter.generate", new=fake_generate), \
         patch.object(agents_service.LiveContextBuilder, "build", new=_stub_build):
        async with AsyncSessionLocal() as session:
            result = await agents_service.analyze(
                session, persona_id="buffett", symbol="AAPL", question=None,
            )
            assert result["persona_id"] == "buffett"
            assert result["verdict"] == "buy"
            assert round(result["confidence"], 4) == 0.72
            assert "Stubbed reasoning" in result["reasoning_summary"]

            from sqlalchemy import select
            rows = (await session.execute(select(AgentAnalysis))).scalars().all()
            assert len(rows) == 1
            assert rows[0].symbol == "AAPL"


@pytest.mark.asyncio
async def test_council_runs_multiple_personas() -> None:
    from app.services import agents_service

    async def fake_generate(self, *, system, user, model=None):
        from core.agents.llm_router import LLMResponse
        return LLMResponse(text=_stub_response_json("hold", 0.6), model="stub")

    with patch("core.agents.OpenAILLMRouter.generate", new=fake_generate), \
         patch.object(agents_service.LiveContextBuilder, "build", new=_stub_build):
        async with AsyncSessionLocal() as session:
            result = await agents_service.council(
                session,
                persona_ids=["buffett", "graham", "sentinel"],
                symbol="MSFT",
                question="Long-term hold?",
            )
            assert len(result["analyses"]) == 3
            assert {a["persona_id"] for a in result["analyses"]} == {"buffett", "graham", "sentinel"}


@pytest.mark.asyncio
async def test_list_history_filters_by_symbol() -> None:
    from app.services import agents_service

    async with AsyncSessionLocal() as session:
        for symbol, persona in [("AAPL", "buffett"), ("AAPL", "graham"), ("MSFT", "buffett")]:
            session.add(AgentAnalysis(
                persona_id=persona, symbol=symbol, verdict="buy", confidence=0.7,
                reasoning_summary="x",
            ))
        await session.commit()
        rows = await agents_service.list_history(session, symbol="AAPL", limit=20)
        assert len(rows) == 2
        assert all(r["symbol"] == "AAPL" for r in rows)


@pytest.mark.asyncio
async def test_list_personas_view_returns_all_six() -> None:
    from app.services import agents_service

    views = agents_service.list_personas_view()
    assert len(views) == 6
    ids = [v["id"] for v in views]
    assert "sentinel" in ids
    assert all("system_prompt" not in v for v in views)
