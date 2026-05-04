# Personal Automated Trading Platform

FastAPI + React trading workspace for paper-trading execution, AI-assisted monitoring, and GitHub-friendly deployment. The project is packaged so another user can deploy it from GitHub, open a browser, fill in API keys on a settings page, and start using the dashboard without editing server-side `.env` files.

> Paper trading only. The monitoring, candidate-pool, universe-search, and social-intelligence layers are read-only. The strategy runner is designed for Alpaca paper accounts and should not be pointed at a live brokerage account without additional risk controls.

## Highlights

- GitHub-ready deployment with `Dockerfile`, `docker-compose.yml`, GitHub Actions CI, and browser-based runtime configuration.
- FastAPI backend for account state, positions, orders, watchlist management, Alpaca universe search, AI monitoring snapshots, and social search.
- React dashboard with holdings, candidate pool, day/week/month trend comparison, recent orders, news summary, and research panel.
- Daily candidate-pool flow that pre-ranks technology stocks plus QQQ/SPY-style ETFs, then optionally asks OpenAI to choose the final 5 names.
- yfinance-based day-over-day, week-over-week, and month-over-month trend tracking for selected, candidate, and held symbols.
- Tavily-powered news and research summaries, plus optional X search and Chinese digest generation.
- Runtime settings page that stores deployer-provided API keys in SQLite and keeps sensitive values hidden from the browser after save.
- CLI harness in `agent-harness/` for agent-style automation and scripting.

## Repository Layout

```text
trading_platform/
├── .github/workflows/ci.yml
├── backend/
│   ├── app/
│   ├── strategy/
│   ├── tests/
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
├── agent-harness/
├── launcher/
├── Dockerfile
├── docker-compose.yml
├── CONTRIBUTING.md
└── LICENSE
```

## Deploy From GitHub

This repository is ready for Docker-based deployment on platforms that can build from a GitHub repository.

### Minimum host environment variables

- `SETTINGS_ADMIN_TOKEN`

### Recommended host environment variables

- `DATA_DIR`

### First deploy flow

1. Fork or clone the repository.
2. Deploy it on any Docker-capable platform.
3. Set `SETTINGS_ADMIN_TOKEN` on the host.
4. Optionally set `DATA_DIR` so SQLite and runtime settings live in a persistent volume.
5. Open the deployed URL.
6. If required keys are missing, the app opens the runtime settings page first.
7. Fill in the required API keys from the browser and save.
8. Return to the dashboard.

### Local Docker run

```bash
docker compose up --build
```

## Runtime Configuration

The app supports two configuration paths:

- `backend/.env` for local development
- the in-app runtime settings page for deployed instances

Sensitive keys are never returned to the browser after saving. The UI only reports whether a key is configured and where it came from (`env`, `stored`, or `default`).

### Required keys for a full dashboard

- `ALPACA_API_KEY`
- `ALPACA_SECRET_KEY`
- `POLYGON_API_KEY`
- `TAVILY_API_KEY`

### Optional keys

- `OPENAI_API_KEY`
  Enables AI final selection for the candidate pool and social digest generation.
- `X_BEARER_TOKEN`
  Enables official X Recent Search for the social-intelligence layer.
- `SETTINGS_ADMIN_TOKEN`
  Protects browser-based settings updates on shared or public deployments.

Runtime configuration is stored in SQLite under `DATA_DIR/trading_platform.db` when `DATA_DIR` is set. Otherwise it falls back to `backend/trading_platform.db`.

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

If you want the frontend to target a non-default backend URL:

```bash
export VITE_API_BASE_URL=http://localhost:8000
```

## Desktop App Mode

The project can now run as a native desktop app instead of opening in a browser.

### macOS

Run from source:

```bash
./Trading\ Raven\ Desktop.command
```

Build a real `.app`:

```bash
./launcher/build_desktop_app.sh
```

Build output:

- `output/desktop/Trading Raven Platform.app`

Desktop app data is stored under:

- `~/Library/Application Support/Trading Raven Platform`

### Windows

Run from source:

```bat
Trading Raven Desktop.bat
```

Build a Windows desktop bundle:

```bat
launcher\build_desktop_app.bat
```

Build output:

- `output\desktop-windows\Trading Raven Platform\Trading Raven Platform.exe`

Desktop app data is stored under:

- `%APPDATA%\Trading Raven Platform`

### Notes

- Desktop mode does not open a browser window.
- Desktop launchers install desktop-only Python dependencies (`pywebview`, `pyinstaller`) into `backend/.venv`.
- Production frontend builds now default to same-origin API requests, which lets the packaged desktop app run on a dynamic local port.
- The existing browser-based launchers still work if you prefer the web workspace.

### Strategy Runner

Run this only if you want the Strategy B paper-trading loop:

```bash
cd backend
source .venv/bin/activate
python -m strategy.runner
```

## One-Click Launch on macOS

The repository includes local launchers for Finder:

- `Trading Platform.app`
- `Stop Trading Platform.app`
- `Start Trading Platform.command`
- `Stop Trading Platform.command`

The launcher checks the backend environment, installs dependencies if needed, rebuilds the frontend when sources change, starts FastAPI on `http://127.0.0.1:8000`, and opens the browser automatically.

Runtime files:

- PID file: `.run/backend.pid`
- Backend log: `logs/backend.log`

If macOS blocks the first launch, right-click the `.app` and choose `Open`.

## What The App Does

### Trading workspace

- Shows Alpaca account metrics, current positions, historical trades, and recent orders.
- Supports watchlist management and symbol-specific news/research lookup.
- Exposes bot status plus controls for starting or stopping the paper runner.

### Monitoring layer

- Uses Alpaca to expose a searchable stock universe so users can add any active tradable U.S. symbol to the watchlist.
- Combines watchlist symbols, current positions, and the AI candidate pool into one monitoring view.
- Shows relative performance versus the previous day, previous week, and previous month for each tracked symbol.
- Builds the candidate pool from a curated technology universe plus ETF proxies such as `QQQ`, `SPY`, `VOO`, `XLK`, `VGT`, and `SMH`.
- Falls back to deterministic scoring if OpenAI is unavailable.

### Social-intelligence layer

- `X` is the first working provider.
- Search applies common filters such as `-is:retweet` and `-is:reply`, then ranks posts by engagement, recency, keyword overlap, and author authority.
- OpenAI can optionally generate a short Chinese digest.
- `xiaohongshu` is currently a placeholder provider only. The interface is present, but public-content search is not implemented.

## Key API Endpoints

- `GET /api/account`
- `GET /api/positions`
- `GET /api/trades`
- `GET /api/orders?status=all`
- `GET /api/monitoring`
- `POST /api/monitoring/refresh`
- `GET /api/universe?query=NVDA`
- `POST /api/watchlist`
- `DELETE /api/watchlist/{symbol}`
- `GET /api/settings/status`
- `PUT /api/settings`
- `GET /api/social/providers`
- `GET /api/social/search?query=NVDA+AI&provider=x`

## CLI Harness

This repo includes an agent-native CLI harness inspired by the CLI-Anything workflow.

- Source: `agent-harness/`
- Entry point: `cli-anything-trading-platform`

Install it into the backend environment:

```bash
cd backend
source .venv/bin/activate
cd ../agent-harness
pip install .
```

Examples:

```bash
cli-anything-trading-platform monitoring overview --refresh
cli-anything-trading-platform monitoring candidates
cli-anything-trading-platform universe search NVDA --limit 5
cli-anything-trading-platform watchlist add ABNB
cli-anything-trading-platform bot status
cli-anything-trading-platform app start
cli-anything-trading-platform social providers
cli-anything-trading-platform social search "NVDA AI" --provider x --min-likes 20
cli-anything-trading-platform social digest "美股 AI 芯片" --provider x
```

## Strategy B Summary

- Universe: 20 large-cap U.S. stocks.
- Initial buy: fixed `1000` notional when the symbol drops at least `2%` versus the previous close.
- Add-on buy: fixed `100` notional for each additional `2%` drop, capped at 3 add-ons.
- Exit rules:
  - Take profit at `80` absolute currency units.
  - Stop loss at `12%` of capital committed to that position.
  - Forced exit after `30` calendar days.

## Quality Gates

- GitHub Actions workflow in `.github/workflows/ci.yml`
- Backend unit tests under `backend/tests/`
- Frontend production build via `npm run build`

## Contributing

See `CONTRIBUTING.md` for setup and contribution expectations.

## License

MIT. See `LICENSE`.

## Deploy on Railway

### Single-service Dockerfile deploy

1. Create a new project in Railway, link it to this GitHub repo. Railway auto-detects the `Dockerfile` and `railway.json`.

2. **Add a persistent volume** at `/app/data` (Railway dashboard → service → Settings → Volumes). The factor library, daily bars, and recommendation history live in SQLite at `/app/data/trading_platform.db`. Without the volume every redeploy wipes data.

3. **Set required environment variables** (Settings → Variables):
   - `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` — paper trading + price data
   - `OPENAI_API_KEY` — AI features
   - Optional: `POLYGON_API_KEY`, `TAVILY_API_KEY`, `ANTHROPIC_API_KEY`
   - `CORS_ALLOW_ORIGINS=https://<your-railway-domain>.up.railway.app,https://yourdomain.com`
   - `FACTOR_EVOLUTION_AUTOSTART` — keep `false` to avoid runaway compute; user starts the loop manually via the UI

4. Railway sets `PORT` automatically. The `Dockerfile`'s `CMD` reads it.

5. **Healthcheck** is at `/api/health` (configured in `railway.json`). Railway will retire unhealthy replicas automatically.

### Cost notes

- **Free tier insufficient** — 512MB RAM is too tight for pandas + GP backtests. Use Hobby ($5/mo) minimum; Pro ($20/mo, 8GB) for headroom.
- **Loop default off** — to keep cloud CPU usage near zero until you actively use the dashboard.
- **OpenAI cost** — defaults are `gpt-4o-mini` for high-volume calls (factor variants, Q&A) but `gpt-4o` for vision (chart annotation). Override per-model env vars to tune.
- **yfinance ban risk** — Railway shared IPs sometimes get rate-limited by Yahoo. Configure `POLYGON_API_KEY` for the primary data path; yfinance is the fallback.

### First-boot checklist

- [ ] Volume mounted at `/app/data`
- [ ] `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` set
- [ ] `OPENAI_API_KEY` set
- [ ] `CORS_ALLOW_ORIGINS` restricted to your domain
- [ ] `/api/health` returns 200 (Railway will block deploy otherwise)
- [ ] Visit `/factors` and trigger initial data backfill via the button
- [ ] Start factor evolution loop manually when ready

