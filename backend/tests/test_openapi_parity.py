"""Lock the public route inventory. If a refactor adds/removes a route by
accident, this test fails and forces the change to be intentional."""
from __future__ import annotations

EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET",    "/api/account"),
    ("GET",    "/api/agents/history"),
    ("GET",    "/api/agents/personas"),
    ("POST",   "/api/agents/analyze"),
    ("POST",   "/api/agents/council"),
    ("GET",    "/api/positions"),
    ("GET",    "/api/trades"),
    ("GET",    "/api/orders"),
    ("POST",   "/api/orders/cancel"),
    ("POST",   "/api/positions/close"),
    ("GET",    "/api/monitoring"),
    ("POST",   "/api/monitoring/refresh"),
    ("GET",    "/api/universe"),
    ("POST",   "/api/watchlist"),
    ("DELETE", "/api/watchlist/{symbol}"),
    ("GET",    "/api/news/{symbol}"),
    ("GET",    "/api/research/{symbol}"),
    ("GET",    "/api/tavily/search"),
    ("GET",    "/api/chart/{symbol}"),
    ("GET",    "/api/company/{symbol}"),
    ("GET",    "/api/health"),
    ("GET",    "/api/health/ready"),
    ("GET",    "/api/strategy/health"),
    ("GET",    "/api/strategies"),
    ("GET",    "/api/strategies/registered"),
    ("POST",   "/api/strategies"),
    ("POST",   "/api/strategies/analyze"),
    ("POST",   "/api/strategies/analyze-upload"),
    ("POST",   "/api/strategies/analyze-factor-code"),
    ("POST",   "/api/strategies/analyze-factor-upload"),
    ("PUT",    "/api/strategies/{strategy_id}"),
    ("POST",   "/api/strategies/preview"),
    ("POST",   "/api/strategies/{strategy_id}/activate"),
    ("DELETE", "/api/strategies/{strategy_id}"),
    ("GET",    "/api/alerts"),
    ("POST",   "/api/alerts"),
    ("PATCH",  "/api/alerts/{rule_id}"),
    ("DELETE", "/api/alerts/{rule_id}"),
    ("POST",   "/api/backtest/run"),
    ("GET",    "/api/backtest/runs"),
    ("GET",    "/api/backtest/{run_id}"),
    ("GET",    "/api/backtest/{run_id}/equity-curve"),
    ("POST",   "/api/quantlib/bond/risk"),
    ("POST",   "/api/quantlib/bond/yield"),
    ("POST",   "/api/quantlib/option/greeks"),
    ("POST",   "/api/quantlib/option/price"),
    ("POST",   "/api/quantlib/var"),
    ("GET",    "/api/code/strategies"),
    ("POST",   "/api/code/upload"),
    ("GET",    "/api/code/strategies/{strategy_id}/source"),
    ("POST",   "/api/code/strategies/{strategy_id}/reload"),
    ("DELETE", "/api/code/strategies/{strategy_id}"),
    ("GET",    "/api/risk/policies"),
    ("PUT",    "/api/risk/policies"),
    ("GET",    "/api/risk/events"),
    ("GET",    "/api/social/providers"),
    ("GET",    "/api/social/search"),
    ("GET",    "/api/social/score"),
    ("GET",    "/api/social/signals"),
    ("POST",   "/api/social/run"),
    ("GET",    "/api/bot/status"),
    ("POST",   "/api/bot/start"),
    ("POST",   "/api/bot/stop"),
    ("GET",    "/api/settings/status"),
    ("PUT",    "/api/settings"),
    # --- Investment journal CRUD + symbol autocomplete ---
    ("GET",    "/api/journal"),
    ("POST",   "/api/journal"),
    ("GET",    "/api/journal/{entry_id}"),
    ("PATCH",  "/api/journal/{entry_id}"),
    ("DELETE", "/api/journal/{entry_id}"),
    ("GET",    "/api/journal/symbols/autocomplete"),
    # --- Tradewell-inspired additions (macro / valuation / options-chain) ---
    ("GET",    "/api/macro"),
    ("POST",   "/api/macro/refresh"),
    ("GET",    "/api/macro/calendar"),
    ("PUT",    "/api/macro/indicators/{code}/thresholds"),
    ("DELETE", "/api/macro/indicators/{code}/thresholds"),
    ("POST",   "/api/valuation/dcf"),
    ("GET",    "/api/valuation/pe-channel/{ticker}"),
    ("GET",    "/api/options-chain/{ticker}"),
    ("POST",   "/api/options-chain/{ticker}/refresh"),
    ("GET",    "/api/options-chain/{ticker}/expiry/{expiry}"),
    ("GET",    "/api/options-chain/{ticker}/friday-scan"),
    ("GET",    "/api/options-chain/{ticker}/squeeze"),
    ("GET",    "/api/options-chain/{ticker}/structure"),
    ("GET",    "/api/options-chain/{ticker}/clusters"),
    ("GET",    "/api/options-chain/{ticker}/oi-float"),
    ("GET",    "/api/options-chain/{ticker}/iv-surface"),
    # --- TradingView pine-seeds workspace ---
    ("GET",    "/api/pine-seeds/status"),
    ("POST",   "/api/pine-seeds/export"),
    # --- Sector rotation ---
    ("GET",    "/api/sectors/rotation"),
    ("POST",   "/api/sectors/rotation/refresh"),
    # --- Multi-asset screener ---
    ("GET",    "/api/screener"),
    ("POST",   "/api/screener/refresh"),
    # --- CoinGecko crypto markets (opt-in) ---
    ("GET",    "/api/crypto/markets"),
    # --- DBnomics public series adapter ---
    ("GET",    "/api/dbnomics/series/{provider}/{dataset}/{series_id}"),
    # --- Raw headlines aggregator ---
    ("GET",    "/api/news/{symbol}/headlines"),
    # --- Geopolitical risk events ---
    ("GET",    "/api/geopolitics/events"),
    # --- Polymarket prediction markets (opt-in) ---
    ("GET",    "/api/predictions/markets"),
    # --- News clustering (NLP) ---
    ("GET",    "/api/news/{symbol}/clusters"),
    # --- Docs panel ---
    ("GET",    "/api/docs/list"),
    ("GET",    "/api/docs/{slug}"),
}


def test_route_inventory_unchanged() -> None:
    from app.main import app

    actual: set[tuple[str, str]] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path or not path.startswith("/api/"):
            continue
        for method in methods:
            actual.add((method, path))

    missing = EXPECTED_ROUTES - actual
    extra = actual - EXPECTED_ROUTES
    assert not missing, f"Routes dropped by refactor: {sorted(missing)}"
    assert not extra, f"Routes unexpectedly added: {sorted(extra)}"
