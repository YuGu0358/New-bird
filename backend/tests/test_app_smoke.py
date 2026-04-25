"""Integration smoke tests: one no-network endpoint per future router boundary.

These run against the live FastAPI app via TestClient. Goal: prove the router
split in this PR does not change route paths, methods, or response shapes.
"""
from __future__ import annotations


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
    from app.main import strategy_profiles_service

    async def _list_strategies(_session):
        return {"max_slots": 5, "items": [], "active_strategy_id": None}

    monkeypatch.setattr(strategy_profiles_service, "list_strategies", _list_strategies)

    response = client.get("/api/strategies")
    assert response.status_code == 200
    body = response.json()
    assert "items" in body


def test_unknown_route_returns_404_or_spa_index(client) -> None:
    """The SPA fallback at `/{full_path:path}` may serve index.html if the
    frontend dist exists, else 404. Either is acceptable; we only assert the
    server doesn't 500."""
    response = client.get("/this-route-does-not-exist-xyz")
    assert response.status_code in (200, 404)
