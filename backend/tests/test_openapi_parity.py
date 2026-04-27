"""Lock the public route inventory. If a refactor adds/removes a route by
accident, this test fails and forces the change to be intentional."""
from __future__ import annotations

EXPECTED_ROUTES: set[tuple[str, str]] = {
    ("GET",    "/api/account"),
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
