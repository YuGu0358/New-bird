"""Tests for the Phase 6.3 MCP server.

These tests deliberately do NOT spawn a subprocess — that would be slow
and flaky. Instead they import `build_server` and inspect the FastMCP
instance directly, then call individual tool functions with monkeypatched
service dependencies.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any

import pytest

from app.mcp import server as mcp_server
from app.mcp.server import SERVER_NAME, build_server

EXPECTED_TOOLS = (
    "get_account_summary",
    "list_positions",
    "search_universe",
    "get_recent_news",
    "get_monitoring_overview",
    "get_workspace_state",
)


def _get_registered_tool(server: Any, name: str) -> Any:
    """Look up a registered tool through the FastMCP tool manager."""
    return server._tool_manager.get_tool(name)


def test_build_server_is_pure_factory() -> None:
    """Building twice yields independent instances; no module side effects."""
    a = build_server()
    b = build_server()
    assert a is not b
    assert a.name == SERVER_NAME == "newbird-trading"


def test_all_expected_tools_registered() -> None:
    """The six Phase 6.3 tools are present and no extras leaked in."""
    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS)


def test_each_tool_is_async_with_docstring() -> None:
    """Every registered tool's underlying fn is a coroutine with a docstring."""
    server = build_server()
    for name in EXPECTED_TOOLS:
        tool = _get_registered_tool(server, name)
        assert tool is not None, f"missing tool: {name}"
        assert tool.is_async is True, f"tool {name} is not async"
        # The exception-wrapper preserves the original via functools.wraps,
        # but the registered fn is the wrapper. Both should be coroutines.
        assert inspect.iscoroutinefunction(tool.fn), (
            f"tool {name} fn is not a coroutine"
        )
        # Docstring is forwarded to the AI client as the tool description.
        assert (tool.description or "").strip(), f"tool {name} has no docstring"


def test_health_resource_registered() -> None:
    """The static health resource is exposed at the documented URI."""
    server = build_server()
    resources = asyncio.run(server.list_resources())
    uris = {str(r.uri) for r in resources}
    assert "newbird://config/health" in uris


@pytest.mark.asyncio
async def test_get_workspace_state_returns_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: monkeypatch the service, assert the tool's return shape."""
    fixed_payload = {
        "id": 7,
        "name": "Trading Desk",
        "state": {"layout": "two-pane"},
        "created_at": None,
        "updated_at": None,
    }

    async def fake_get_workspace(session: Any, name: str) -> dict[str, Any]:
        assert name == "Trading Desk"
        return fixed_payload

    monkeypatch.setattr(
        mcp_server.workspace_service, "get_workspace", fake_get_workspace
    )

    server = build_server()
    result = await server.call_tool(
        "get_workspace_state", {"name": "Trading Desk"}
    )
    # FastMCP returns (content_list, structured_result). Structured result
    # is the dict shape declared by the tool's return annotation.
    _content, structured = result
    assert structured == fixed_payload


@pytest.mark.asyncio
async def test_get_workspace_state_handles_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Returning None from the service surfaces a structured error string."""

    async def fake_get_workspace(session: Any, name: str) -> None:
        return None

    monkeypatch.setattr(
        mcp_server.workspace_service, "get_workspace", fake_get_workspace
    )

    server = build_server()
    _content, structured = await server.call_tool(
        "get_workspace_state", {"name": "nope"}
    )
    assert isinstance(structured, dict)
    assert "error" in structured
    assert "nope" in structured["error"]


@pytest.mark.asyncio
async def test_safe_wrapper_catches_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the wrapped service raises, the tool returns {error: ...} instead."""

    async def boom(session: Any, name: str) -> dict[str, Any]:
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(
        mcp_server.workspace_service, "get_workspace", boom
    )

    server = build_server()
    _content, structured = await server.call_tool(
        "get_workspace_state", {"name": "anything"}
    )
    assert isinstance(structured, dict)
    assert "error" in structured
    assert "RuntimeError" in structured["error"]
    assert "simulated DB outage" in structured["error"]


@pytest.mark.asyncio
async def test_search_universe_clamps_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wrapper clamps `limit` into [1, 200] before delegating."""
    captured: dict[str, Any] = {}

    async def fake_search(*, query: str, limit: int) -> list[dict[str, Any]]:
        captured["query"] = query
        captured["limit"] = limit
        return [{"symbol": "AAPL", "name": "Apple Inc."}]

    monkeypatch.setattr(
        mcp_server.watchlist_module, "search_alpaca_universe", fake_search
    )

    server = build_server()
    # 9999 should clamp to 200; -5 should clamp to 1.
    await server.call_tool("search_universe", {"query": "app", "limit": 9999})
    assert captured["limit"] == 200

    await server.call_tool("search_universe", {"query": "app", "limit": -5})
    assert captured["limit"] == 1
    assert captured["query"] == "app"
