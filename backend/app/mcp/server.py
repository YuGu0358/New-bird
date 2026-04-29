"""MCP (Model Context Protocol) server exposing read-only NewBird APIs.

Phase 6.3 — runs over stdio JSON-RPC. AI clients (Claude Desktop, Claude
Code, internal AI Council) launch this as a subprocess via:

    python -m app.mcp.server

The server registers a curated subset of platform read APIs as MCP tools
that wrap existing FastAPI services. No business logic is reimplemented
here — every tool delegates to a `services/*` function.

Design notes:
- `build_server()` is a pure factory so tests can inspect tools without
  spawning a subprocess and without triggering network calls at import.
- Tools that need a DB session open one via `AsyncSessionLocal` (the same
  factory that `get_session` yields from in routers) — there is no
  FastAPI request scope here.
- Tools that need API keys rely on the underlying services, which already
  read through `runtime_settings`. Wrappers stay thin.
- All tools catch exceptions and return `{"error": "..."}` rather than
  raising, so a single misbehaving call cannot kill the long-lived
  stdio server.
"""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from mcp.server.fastmcp import FastMCP

from app.db import AsyncSessionLocal
from app.services import (
    alpaca_service,
    monitoring_service,
    tavily_service,
    workspace_service,
)
from app.services.monitoring import watchlist as watchlist_module

logger = logging.getLogger(__name__)

SERVER_NAME = "newbird-trading"
SERVER_VERSION = "1.0.0"

T = TypeVar("T")


def _safe(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[Any]]:
    """Wrap an async tool so unexpected errors become structured payloads.

    A long-lived MCP server should never crash on a single bad call —
    surface failures as data the client can render.
    """

    @wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — broad on purpose at boundary
            logger.exception("MCP tool %s failed", fn.__name__)
            return {"error": f"{type(exc).__name__}: {exc}"}

    return wrapper


def build_server() -> FastMCP:
    """Construct the FastMCP instance with all tools and resources.

    Pure factory — safe to call from tests. No network calls happen here;
    they only happen when a tool is actually invoked.
    """
    server = FastMCP(SERVER_NAME)

    @server.tool()
    @_safe
    async def get_account_summary() -> dict[str, Any]:
        """Return the configured Alpaca paper account summary.

        Includes equity, buying power, cash, portfolio value, and account
        status. Read-only.
        """
        return await alpaca_service.get_account()

    @server.tool()
    @_safe
    async def list_positions() -> list[dict[str, Any]]:
        """Return current open positions on the Alpaca paper account.

        Each position includes symbol, qty, average entry price, market
        value, and unrealized P&L.
        """
        return await alpaca_service.list_positions()

    @server.tool()
    @_safe
    async def search_universe(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search the tradable U.S. equity universe by symbol or name.

        Args:
            query: Substring to match against symbol or company name.
            limit: Maximum number of matches (1-200, default 10).
        """
        bounded_limit = max(1, min(int(limit), 200))
        return await watchlist_module.search_alpaca_universe(
            query=query, limit=bounded_limit
        )

    @server.tool()
    @_safe
    async def get_recent_news(symbol: str, limit: int = 5) -> dict[str, Any]:
        """Return a recent-news summary for a single ticker via Tavily.

        Args:
            symbol: Ticker symbol (e.g. "AAPL"). Case-insensitive.
            limit: Reserved for future fan-out; current implementation
                returns one consolidated summary block from Tavily.
        """
        # `limit` is accepted for forward-compat; the underlying service
        # already caps internal sources. Touching it keeps the arg from
        # being flagged unused.
        _ = max(1, int(limit))
        return await tavily_service.fetch_news_summary(symbol)

    @server.tool()
    @_safe
    async def get_monitoring_overview() -> dict[str, Any]:
        """Return the unified watchlist + candidate pool + positions view.

        Mirrors `/api/monitoring/overview` (the monitoring dashboard
        payload). Opens a short-lived DB session.
        """
        async with AsyncSessionLocal() as session:
            return await monitoring_service.get_monitoring_overview(session)

    @server.tool()
    @_safe
    async def get_workspace_state(name: str) -> dict[str, Any]:
        """Return a saved UI workspace state by name.

        Args:
            name: Exact workspace name (unique key in the
                `user_workspaces` table).

        Returns the workspace dict, or `{"error": "..."}` if not found.
        """
        async with AsyncSessionLocal() as session:
            payload = await workspace_service.get_workspace(session, name)
        if payload is None:
            return {"error": f"workspace not found: {name}"}
        return payload

    @server.resource("newbird://config/health")
    def health_resource() -> dict[str, Any]:
        """Static health/version probe for clients verifying the server."""
        return {"status": "ok", "version": SERVER_VERSION}

    return server


def main() -> None:
    """Entry point — `python -m app.mcp.server`."""
    logging.basicConfig(level=logging.INFO)
    server = build_server()
    server.run()  # blocks; reads JSON-RPC from stdin, writes to stdout


if __name__ == "__main__":
    main()
