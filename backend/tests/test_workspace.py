"""Service- and router-level tests for the workspace save/load surface (Phase 7.3).

Mirrors the in-memory SQLite fixture pattern from
`test_position_overrides.py` so each test starts with an empty
`user_workspaces` table.

The tests use `TestClient(app)` without `with` — bypasses the FastAPI
lifespan (no scheduler / polygon WS startup) per the convention in
`test_scheduler.py`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so workspace rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import AsyncSessionLocal

    original_engine = engine_module.engine
    db_path = tmp_path / "workspace.db"
    new_engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}", echo=False, future=True
    )
    new_session_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    monkeypatch.setattr(engine_module, "engine", new_engine)
    monkeypatch.setattr(engine_module, "AsyncSessionLocal", new_session_factory)
    from app import database as legacy
    monkeypatch.setattr(legacy, "AsyncSessionLocal", new_session_factory)
    AsyncSessionLocal.configure(bind=new_engine)

    async with new_engine.begin() as conn:
        await conn.run_sync(engine_module.Base.metadata.create_all)
    yield
    AsyncSessionLocal.configure(bind=original_engine)
    await new_engine.dispose()


def _client() -> TestClient:
    """Build a bare TestClient — no lifespan, matches test_scheduler.py."""
    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Empty list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_empty_returns_empty_array() -> None:
    client = _client()
    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    assert resp.json() == {"workspaces": []}


# ---------------------------------------------------------------------------
# 2. PUT inserts a new workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_creates_workspace() -> None:
    client = _client()
    payload = {
        "name": "Layout-A",
        "state": {"activeTab": "watchlist", "ticker": "AAPL"},
    }
    resp = client.put("/api/workspaces", json=payload)
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["name"] == "Layout-A"
    assert body["state"] == {"activeTab": "watchlist", "ticker": "AAPL"}
    assert body["id"] > 0
    assert body["created_at"] is not None
    assert body["updated_at"] is not None

    # And the GET list reflects it.
    list_resp = client.get("/api/workspaces")
    assert list_resp.status_code == 200
    items = list_resp.json()["workspaces"]
    assert len(items) == 1
    assert items[0]["name"] == "Layout-A"


# ---------------------------------------------------------------------------
# 3. PUT with the same name replaces the previous state in place
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_replaces_existing_by_name() -> None:
    client = _client()
    first = client.put(
        "/api/workspaces",
        json={"name": "Layout-A", "state": {"version": 1}},
    )
    assert first.status_code == 200
    first_id = first.json()["id"]

    second = client.put(
        "/api/workspaces",
        json={"name": "Layout-A", "state": {"version": 2, "extra": True}},
    )
    assert second.status_code == 200
    second_body = second.json()

    # Same row id -> upsert, not duplicate insert.
    assert second_body["id"] == first_id
    assert second_body["state"] == {"version": 2, "extra": True}

    # Only one row total.
    list_resp = client.get("/api/workspaces")
    assert len(list_resp.json()["workspaces"]) == 1


# ---------------------------------------------------------------------------
# 4. GET /{name} returns the saved workspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_name_returns_workspace() -> None:
    client = _client()
    client.put(
        "/api/workspaces",
        json={"name": "Trading View", "state": {"theme": "dark"}},
    )

    resp = client.get("/api/workspaces/Trading View")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Trading View"
    assert body["state"] == {"theme": "dark"}


# ---------------------------------------------------------------------------
# 5. GET unknown name -> 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_unknown_returns_404() -> None:
    client = _client()
    resp = client.get("/api/workspaces/does-not-exist")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 6. DELETE removes the workspace and is idempotent (404 on second call)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_workspace() -> None:
    client = _client()
    client.put(
        "/api/workspaces",
        json={"name": "To-Delete", "state": {"x": 1}},
    )

    del_resp = client.delete("/api/workspaces/To-Delete")
    assert del_resp.status_code == 204

    # Confirm gone.
    get_resp = client.get("/api/workspaces/To-Delete")
    assert get_resp.status_code == 404

    list_resp = client.get("/api/workspaces")
    assert list_resp.json() == {"workspaces": []}


# ---------------------------------------------------------------------------
# 7. DELETE unknown -> 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_unknown_returns_404() -> None:
    client = _client()
    resp = client.delete("/api/workspaces/never-existed")
    assert resp.status_code == 404
