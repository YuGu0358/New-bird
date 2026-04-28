"""Integration smoke tests: one no-network endpoint per future router boundary.

These run against the live FastAPI app via TestClient. Goal: prove the router
split in this PR does not change route paths, methods, or response shapes.
"""
from __future__ import annotations

import pytest


def test_settings_status_returns_dict_shape(client) -> None:
    response = client.get("/api/settings/status")
    assert response.status_code == 200
    body = response.json()
    assert "is_ready" in body
    assert "items" in body
    assert isinstance(body["items"], list)


def test_social_providers_returns_list(client) -> None:
    response = client.get("/api/social/providers")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_bot_status_returns_state(client) -> None:
    response = client.get("/api/bot/status")
    assert response.status_code == 200
    assert "is_running" in response.json()


def test_strategies_library_returns_payload(client, monkeypatch) -> None:
    from app.services import strategy_profiles_service

    async def _list_strategies(_session):
        return {"max_slots": 5, "items": [], "active_strategy_id": None}

    monkeypatch.setattr(strategy_profiles_service, "list_strategies", _list_strategies)

    response = client.get("/api/strategies")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_strategies_registered_lists_strategy_b(client) -> None:
    response = client.get("/api/strategies/registered")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    names = [item["name"] for item in body["items"]]
    assert "strategy_b_v1" in names
    strategy_b = next(item for item in body["items"] if item["name"] == "strategy_b_v1")
    assert strategy_b["description"]
    assert "properties" in strategy_b["parameters_schema"]


def test_unknown_route_returns_404_or_spa_index(client) -> None:
    """The SPA fallback at `/{full_path:path}` may serve index.html if the
    frontend dist exists, else 404. Either is acceptable; we only assert the
    server doesn't 500."""
    response = client.get("/this-route-does-not-exist-xyz")
    assert response.status_code in (200, 404)


def test_account_endpoint_responds(client, monkeypatch) -> None:
    """`/api/account` should return 200 when alpaca_service.get_account is
    mocked, or 503 with a friendly detail when it raises."""
    from app.services import alpaca_service

    async def fake_get_account():
        return {
            "account_id": "",
            "equity": 0.0,
            "buying_power": 0.0,
            "cash": 0.0,
            "portfolio_value": 0.0,
            "day_trade_count": 0,
            "status": "PAPER_OK",
            "last_equity": 0.0,
        }

    monkeypatch.setattr(alpaca_service, "get_account", fake_get_account)
    response = client.get("/api/account")
    assert response.status_code in (200, 503)
    if response.status_code == 200:
        assert "equity" in response.json()


def test_monitoring_endpoint_wired(client, monkeypatch) -> None:
    from app.services import monitoring_service

    async def fake_overview(*args, **kwargs):
        return {"items": [], "candidates": [], "watchlist": [], "positions": []}

    for name in ("get_overview", "build_overview", "load_overview", "refresh_overview"):
        if hasattr(monitoring_service, name):
            monkeypatch.setattr(monitoring_service, name, fake_overview)

    response = client.get("/api/monitoring")
    assert response.status_code in (200, 503)


def test_company_endpoint_wired(client, monkeypatch) -> None:
    from datetime import datetime, timezone

    from app.services import company_profile_service

    async def fake_profile(symbol: str):
        return {
            "symbol": symbol,
            "company_name": symbol,
            "business_summary": "",
            "generated_at": datetime.now(timezone.utc),
        }

    if hasattr(company_profile_service, "get_company_profile"):
        monkeypatch.setattr(company_profile_service, "get_company_profile", fake_profile)
    response = client.get("/api/company/AAPL")
    assert response.status_code in (200, 503)


def test_alerts_list_responds(client, monkeypatch) -> None:
    from app.services import price_alerts_service

    async def fake_list(*args, **kwargs):
        return []

    for name in ("list_rules", "get_rules", "list_alerts"):
        if hasattr(price_alerts_service, name):
            monkeypatch.setattr(price_alerts_service, name, fake_list)
    response = client.get("/api/alerts")
    assert response.status_code in (200, 503)


def test_backtest_runs_list_responds(client) -> None:
    response = client.get("/api/backtest/runs")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_risk_policies_endpoint(client) -> None:
    response = client.get("/api/risk/policies")
    assert response.status_code == 200
    body = response.json()
    assert "enabled" in body
    assert "blocklist" in body


def test_risk_events_endpoint(client) -> None:
    response = client.get("/api/risk/events")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_health_liveness(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body


def test_health_readiness(client) -> None:
    response = client.get("/api/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "ready" in body
    assert "checks" in body
    assert any(c["name"] == "database" for c in body["checks"])


def test_health_readiness_includes_ibkr_check(client) -> None:
    """The IBKR reachability check should appear in the readiness payload."""
    response = client.get("/api/health/ready")
    assert response.status_code in (200, 503)  # ok if all green, 503 if any check failed
    body = response.json()
    check_names = {c["name"] for c in body.get("checks", [])}
    assert "ibkr.reachable" in check_names


def test_metrics_endpoint(client) -> None:
    # Hit a few endpoints first so counters have non-zero values.
    client.get("/api/health")
    client.get("/api/settings/status")

    response = client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_strategy_health_endpoint(client) -> None:
    response = client.get("/api/strategy/health")
    assert response.status_code == 200
    body = response.json()
    for field in (
        "active_strategy_name", "realized_pnl_today", "trades_today",
        "streak_kind", "streak_length", "open_position_count",
    ):
        assert field in body


def test_agents_personas_endpoint(client) -> None:
    response = client.get("/api/agents/personas")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    ids = [p["id"] for p in body["items"]]
    assert {"buffett", "graham", "lynch", "soros", "burry", "sentinel"} <= set(ids)


def test_agents_history_endpoint(client) -> None:
    response = client.get("/api/agents/history")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_quantlib_option_price_endpoint(client) -> None:
    response = client.post("/api/quantlib/option/price", json={
        "spot": 100, "strike": 100, "rate": 0.05, "volatility": 0.20,
        "valuation": "2025-01-01", "expiry": "2026-01-01",
        "right": "call", "style": "european",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["price"] > 0
    assert body["right"] == "call"


def test_quantlib_var_endpoint(client) -> None:
    response = client.post("/api/quantlib/var", json={
        "method": "parametric",
        "notional": 1_000_000,
        "mean_return": 0,
        "std_return": 0.01,
        "confidence": 0.95,
        "horizon_days": 1,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["var"] > 0
    assert body["cvar"] >= body["var"]


def test_code_strategies_endpoint(client) -> None:
    response = client.get("/api/code/strategies")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body
    assert isinstance(body["items"], list)


def test_journal_get_missing_returns_404(client) -> None:
    """Routing-level smoke: GET on a non-existent id returns 404 (not 405/422).

    NOTE: We do not test the empty-list happy path here because the smoke-test
    `client` fixture intentionally skips the lifespan, so the journal_entries
    table is not guaranteed to exist. Service-level tests at
    `test_journal_service.py` cover the empty-list contract under proper DB
    isolation.
    """
    response = client.get("/api/journal/999999")
    # 404 from "not found" or 503 from missing-table (pre-init backend) are
    # both acceptable — the point is the route is registered and not 405.
    assert response.status_code in (404, 503)


def test_journal_create_invalid_mood_returns_422(client) -> None:
    """Pydantic enforces the Literal mood — unknown values fail at request
    validation (422) BEFORE touching the service layer or the DB. This test
    works regardless of DB-init state."""
    response = client.post(
        "/api/journal",
        json={"title": "x", "body": "y", "mood": "ecstatic"},
    )
    assert response.status_code == 422
