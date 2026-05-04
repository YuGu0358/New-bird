"""Alpha Arena service tests — scoreboard math + run dispatching.

Mirrors the in-memory SQLite fixture from ``test_workflow_service.py`` /
``test_workspace.py`` so each test starts with an empty agent_analyses table.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.database import AgentAnalysis, AsyncSessionLocal


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so AgentAnalysis rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "arena.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True,
    )
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


def _chart_payload(prices_by_date: dict[datetime, float]) -> dict:
    """Build a chart_service-shaped payload from a {date: close} mapping."""
    points = [
        {
            "timestamp": ts,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 1000,
        }
        for ts, price in sorted(prices_by_date.items(), key=lambda kv: kv[0])
    ]
    return {
        "symbol": "TEST",
        "range": "1y",
        "interval": "1d",
        "generated_at": datetime.now(timezone.utc),
        "latest_price": points[-1]["close"] if points else 0.0,
        "range_change_percent": None,
        "points": points,
    }


@pytest.mark.asyncio
async def test_get_scoreboard_empty_returns_zero_rows() -> None:
    """No AgentAnalysis rows → every persona shows 0 calls and null metrics."""
    from app.services import arena_service

    async with AsyncSessionLocal() as session:
        result = await arena_service.get_scoreboard(session, lookback_days=30)

    assert result["lookback_days"] == 30
    # Even with no rows, scoreboard always covers the six builtin personas
    # so the UI can render a stable grid.
    assert len(result["scoreboard"]) >= 6
    for entry in result["scoreboard"]:
        assert entry["buy_calls"] == 0
        assert entry["sell_calls"] == 0
        assert entry["hold_calls"] == 0
        assert entry["hit_rate_pct"] is None
        assert entry["avg_buy_pnl_pct"] is None


@pytest.mark.asyncio
async def test_get_scoreboard_computes_hit_rate() -> None:
    """One buy that wins, one buy that loses, one hold — verify aggregates."""
    from app.services import arena_service, chart_service

    now = datetime.now(timezone.utc)
    entry_date = now - timedelta(days=20)
    earlier = now - timedelta(days=21)

    # Stub chart so each symbol's entry close is deterministic and the
    # most-recent point reflects the current price.
    aapl_chart = _chart_payload({
        earlier: 100.0,
        entry_date: 100.0,
        now: 120.0,  # +20% → counts as a "hit"
    })
    nvda_chart = _chart_payload({
        earlier: 200.0,
        entry_date: 200.0,
        now: 180.0,  # -10% → not a hit
    })

    async def fake_chart(symbol, range_name="1y"):
        if symbol == "AAPL":
            return aapl_chart
        if symbol == "NVDA":
            return nvda_chart
        raise ValueError(f"unexpected symbol {symbol}")

    async with AsyncSessionLocal() as session:
        session.add_all([
            AgentAnalysis(
                persona_id="buffett", symbol="AAPL", verdict="buy",
                confidence=0.8, reasoning_summary="winner", created_at=entry_date,
            ),
            AgentAnalysis(
                persona_id="buffett", symbol="NVDA", verdict="buy",
                confidence=0.7, reasoning_summary="loser", created_at=entry_date,
            ),
            AgentAnalysis(
                persona_id="buffett", symbol="MSFT", verdict="hold",
                confidence=0.5, reasoning_summary="hold", created_at=entry_date,
            ),
        ])
        await session.commit()

        with patch.object(chart_service, "get_symbol_chart", side_effect=fake_chart):
            result = await arena_service.get_scoreboard(session, lookback_days=90)

    buffett = next(e for e in result["scoreboard"] if e["persona_id"] == "buffett")
    assert buffett["buy_calls"] == 2
    assert buffett["hold_calls"] == 1
    assert buffett["sell_calls"] == 0
    assert buffett["hits"] == 1  # only AAPL crossed +2%
    assert buffett["hit_rate_pct"] == pytest.approx(50.0)
    # avg of (+20%, -10%) = +5%
    assert buffett["avg_buy_pnl_pct"] == pytest.approx(5.0, abs=0.001)
    assert buffett["best_call"] is not None
    assert buffett["best_call"]["symbol"] == "AAPL"
    assert buffett["worst_call"]["symbol"] == "NVDA"


@pytest.mark.asyncio
async def test_run_arena_dispatches_per_symbol_per_persona() -> None:
    """Two symbols × two personas → 4 current entries + a populated scoreboard."""
    from app.services import agents_service, arena_service, chart_service

    call_log: list[tuple[str, str]] = []

    async def fake_analyze(session, *, persona_id, symbol, **kwargs):
        call_log.append((persona_id, symbol))
        # Persist a row so the post-run scoreboard sees something.
        row = AgentAnalysis(
            persona_id=persona_id,
            symbol=symbol,
            verdict="buy",
            confidence=0.6,
            reasoning_summary="stub",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        await session.flush()
        return {
            "id": row.id,
            "persona_id": persona_id,
            "symbol": symbol,
            "verdict": "buy",
            "confidence": 0.6,
            "reasoning_summary": "stub",
            "action_plan": None,
            "created_at": row.created_at,
        }

    chart = _chart_payload({
        datetime.now(timezone.utc) - timedelta(days=1): 100.0,
        datetime.now(timezone.utc): 100.0,
    })

    with patch.object(agents_service, "analyze", side_effect=fake_analyze), \
         patch.object(chart_service, "get_symbol_chart", return_value=chart):
        async with AsyncSessionLocal() as session:
            result = await arena_service.run_arena(
                session,
                symbols=["AAPL", "NVDA"],
                persona_ids=["buffett", "graham"],
            )

    assert len(result["current"]) == 4
    pairs = {(c["persona_id"], c["symbol"]) for c in result["current"]}
    assert pairs == {
        ("buffett", "AAPL"),
        ("graham", "AAPL"),
        ("buffett", "NVDA"),
        ("graham", "NVDA"),
    }
    # The scoreboard always exposes the builtin personas — verify both
    # selected personas are in it with non-zero buy_calls.
    sb_by_id = {e["persona_id"]: e for e in result["scoreboard"]}
    assert sb_by_id["buffett"]["buy_calls"] == 2
    assert sb_by_id["graham"]["buy_calls"] == 2
    assert call_log == [
        ("buffett", "AAPL"), ("graham", "AAPL"),
        ("buffett", "NVDA"), ("graham", "NVDA"),
    ]
