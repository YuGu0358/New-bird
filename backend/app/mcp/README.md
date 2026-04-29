# NewBird MCP Server (Phase 6.3)

A Model Context Protocol (MCP) server that exposes a curated subset of the
NewBird trading platform's read-only APIs to AI assistants
(Claude Desktop, Claude Code, internal AI Council, etc.).

It runs over **stdio JSON-RPC** — the standard MCP transport. Clients
launch it as a subprocess; this is **not** a FastAPI router.

## Tools exposed

| Tool | Purpose |
|---|---|
| `get_account_summary` | Alpaca paper account: equity, buying power, cash. |
| `list_positions` | Current open positions with unrealized P&L. |
| `search_universe` | Substring search over the tradable U.S. equity universe. |
| `get_recent_news` | Tavily-powered news summary for a single ticker. |
| `get_monitoring_overview` | Unified watchlist + candidate pool + positions. |
| `get_workspace_state` | Saved UI workspace state by name. |

Plus one resource: `newbird://config/health` for liveness/version probes.

## Wiring it into a client

Add this to `~/.claude.json` (Claude Code) or `claude_desktop_config.json`
(Claude Desktop), under `mcpServers`:

```json
{
  "mcpServers": {
    "newbird-trading": {
      "command": "python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/absolute/path/to/NewBirdClaude/backend"
    }
  }
}
```

If you use the project venv, point `command` at the venv's interpreter
(`/absolute/path/to/NewBirdClaude/backend/.venv/bin/python`) so Alpaca,
Tavily, and the rest of the deps resolve.

## Verifying it works

From the `backend/` directory with the venv active:

```bash
python -m app.mcp.server   # blocks on stdin; Ctrl+C to exit
```

Smoke-test `tools/list` over stdio:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | timeout 5 python -m app.mcp.server | head -20
```

You should see a JSON-RPC response listing all six tool names.

## Caveats

- **Read-only.** No order placement, no writes, no settings mutation
  through MCP for this MVP.
- **Requires the backend venv.** All dependencies (Alpaca SDK, Tavily,
  SQLAlchemy, etc.) must be installed in the Python interpreter the
  client launches.
- **API keys via `runtime_settings`.** Alpaca and Tavily keys are read
  from the platform's runtime settings store (SQLite + OS keyring),
  populated through the browser settings UI. Tools that need keys will
  return `{"error": "..."}` when the key is missing rather than crashing.
- **Not production-grade auth.** stdio MCP trusts whoever spawned the
  process. Don't expose this server over a network without a proper
  authenticated transport.
