"""Unit tests for the pure workflow engine (Phase 5.6).

No DB, no FastAPI — every test injects the three IO hooks
(`fetcher`, `indicator_fn`, `paper_order_fn`) so the engine itself is
exercised in isolation. These run very fast (<10ms each) and cover the
contract the service layer relies on.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.workflow import execute_workflow


# --- Stub IO hooks -------------------------------------------------------

async def _fetcher_const(ticker: str, lookback_days: int) -> list[float]:
    """Returns a deterministic ramp; ticker affects the offset."""
    seed = sum(ord(c) for c in ticker) % 5
    return [100.0 + seed + i for i in range(lookback_days)]


def _indicator_last_price(name: str, period: int, prices: list[float]) -> list[float | None]:
    """Trivial indicator: emits the input series unchanged.

    The engine reads the *last non-None* value as the named scalar, so
    returning the prices themselves makes assertions easy.
    """
    return [float(p) for p in prices]


async def _paper_noop(payload: dict[str, Any]) -> dict[str, Any]:
    return {"accepted": True, "broker": "test-noop"}


# --- Fixtures: definition shorthand -------------------------------------

def _node(node_id: str, node_type: str, **data: Any) -> dict[str, Any]:
    return {"id": node_id, "type": node_type, "position": {"x": 0, "y": 0}, "data": data}


def _edge(eid: str, src: str, dst: str) -> dict[str, str]:
    return {"id": eid, "source": src, "target": dst}


# --- Tests ---------------------------------------------------------------

@pytest.mark.asyncio
async def test_linear_pipeline_runs_to_completion() -> None:
    definition = {
        "nodes": [
            _node("n1", "data-fetch", ticker="SPY", lookback_days=5),
            _node("n2", "indicator", name="rsi", period=2),
            _node("n3", "signal", expr="rsi > 0"),
            _node("n4", "risk-check", max_position_size=1000),
            _node("n5", "order", side="buy", qty=1, paper=True),
        ],
        "edges": [
            _edge("e1", "n1", "n2"),
            _edge("e2", "n2", "n3"),
            _edge("e3", "n3", "n4"),
            _edge("e4", "n4", "n5"),
        ],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is True
    assert [n.node_type for n in result.nodes] == [
        "data-fetch", "indicator", "signal", "risk-check", "order",
    ]
    assert result.nodes[-1].output["dispatched"] is True
    assert result.nodes[-1].output["broker_response"]["broker"] == "test-noop"


@pytest.mark.asyncio
async def test_cycle_detection_fails_cleanly() -> None:
    definition = {
        "nodes": [
            _node("a", "data-fetch", ticker="X", lookback_days=3),
            _node("b", "indicator", name="rsi", period=2),
        ],
        "edges": [_edge("e1", "a", "b"), _edge("e2", "b", "a")],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    assert any("cycle" in (n.error or "").lower() for n in result.nodes)


@pytest.mark.asyncio
async def test_invalid_definition_returns_single_failed_node() -> None:
    definition = {"nodes": "not-a-list", "edges": []}
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    assert len(result.nodes) == 1
    assert result.nodes[0].error is not None


@pytest.mark.asyncio
async def test_signal_true_lets_order_dispatch() -> None:
    definition = {
        "nodes": [
            _node("n1", "data-fetch", ticker="SPY", lookback_days=3),
            _node("n2", "indicator", name="rsi", period=1),
            _node("n3", "signal", expr="rsi > 50"),
            _node("n4", "order", side="buy", qty=1),
        ],
        "edges": [
            _edge("e1", "n1", "n2"),
            _edge("e2", "n2", "n3"),
            _edge("e3", "n3", "n4"),
        ],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    sig = next(n for n in result.nodes if n.node_id == "n3")
    assert sig.output["matched"] is True
    order = next(n for n in result.nodes if n.node_id == "n4")
    assert order.output.get("dispatched") is True


@pytest.mark.asyncio
async def test_signal_false_skips_order() -> None:
    definition = {
        "nodes": [
            _node("n1", "data-fetch", ticker="SPY", lookback_days=3),
            _node("n2", "indicator", name="rsi", period=1),
            _node("n3", "signal", expr="rsi < 0"),
            _node("n4", "order", side="buy", qty=1),
        ],
        "edges": [
            _edge("e1", "n1", "n2"),
            _edge("e2", "n2", "n3"),
            _edge("e3", "n3", "n4"),
        ],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    order = next(n for n in result.nodes if n.node_id == "n4")
    assert order.output.get("skipped") is True
    assert "did not match" in order.output["reason"]


@pytest.mark.asyncio
async def test_signal_unknown_name_errors() -> None:
    definition = {
        "nodes": [
            _node("n1", "data-fetch", ticker="X", lookback_days=2),
            _node("n2", "signal", expr="undefined_name > 0"),
        ],
        "edges": [_edge("e1", "n1", "n2")],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    sig = next(n for n in result.nodes if n.node_id == "n2")
    assert sig.error is not None
    assert result.succeeded is False


@pytest.mark.asyncio
async def test_risk_check_approves_when_no_max_configured() -> None:
    definition = {
        "nodes": [_node("r", "risk-check")],
        "edges": [],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is True
    assert result.nodes[0].output["ok"] is True


@pytest.mark.asyncio
async def test_data_fetch_missing_ticker_errors() -> None:
    definition = {
        "nodes": [_node("n1", "data-fetch", lookback_days=5)],
        "edges": [],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    assert "ticker" in (result.nodes[0].error or "")


@pytest.mark.asyncio
async def test_unknown_node_type_caught_at_parse() -> None:
    definition = {
        "nodes": [{"id": "x", "type": "made-up", "data": {}}],
        "edges": [],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    assert result.nodes[0].node_id == "<definition>"


@pytest.mark.asyncio
async def test_order_node_invalid_side_errors() -> None:
    definition = {
        "nodes": [_node("o", "order", side="hold", qty=1)],
        "edges": [],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    assert "side" in (result.nodes[0].error or "")


@pytest.mark.asyncio
async def test_node_error_does_not_halt_subsequent_nodes() -> None:
    """A failing earlier node still lets independent later nodes run."""
    definition = {
        "nodes": [
            _node("bad", "order", side="bogus", qty=1),
            _node("ok", "risk-check", max_position_size=500),
        ],
        "edges": [],
    }
    result = await execute_workflow(
        definition,
        fetcher=_fetcher_const,
        indicator_fn=_indicator_last_price,
        paper_order_fn=_paper_noop,
    )
    assert result.succeeded is False
    by_id = {n.node_id: n for n in result.nodes}
    assert by_id["bad"].error is not None
    assert by_id["ok"].error is None
    assert by_id["ok"].output["ok"] is True
