# CLI-Anything Trading Platform

This package exposes the local trading platform as an agent-friendly CLI.

Install it from the project root:

```bash
cd agent-harness
pip install .
```

Then use:

```bash
cli-anything-trading-platform --help
cli-anything-trading-platform monitoring overview --refresh
cli-anything-trading-platform universe search NVDA --limit 5
cli-anything-trading-platform watchlist add ABNB
cli-anything-trading-platform bot status
cli-anything-trading-platform social providers
cli-anything-trading-platform social search "NVDA AI" --provider x --min-likes 20
cli-anything-trading-platform social digest "美股 AI 芯片" --provider x
```

If you prefer Finder, you can also double-click:

```bash
./Trading CLI.command
```

The CLI reuses the platform's existing backend services and database through the local HTTP API.
For X search, populate `X_BEARER_TOKEN` in `backend/.env` or through the runtime settings page.
