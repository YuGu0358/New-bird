"""Service + router tests for Phase 5.6 Workflow CRUD/run/enable/disable.

Mirrors `test_workspace.py`'s in-memory SQLite fixture so each test
starts with an empty `workflows` table. Uses `TestClient(app)` without
`with` — bypasses the FastAPI lifespan (no scheduler boot) per the
convention in `test_scheduler.py` and `test_workspace.py`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so workflow rows don't leak across tests."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.database import AsyncSessionLocal

    original_engine = engine_module.engine
    db_path = tmp_path / "workflow.db"
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
    """Build a bare TestClient — no lifespan, matches test_workspace.py."""
    from app.main import app

    return TestClient(app)


def _trivial_definition() -> dict:
    """A one-node graph that runs to completion with no external data."""
    return {
        "nodes": [
            {"id": "r", "type": "risk-check", "position": {"x": 0, "y": 0}, "data": {}}
        ],
        "edges": [],
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_empty_returns_empty_array() -> None:
    client = _client()
    resp = client.get("/api/workflows")
    assert resp.status_code == 200
    assert resp.json() == {"workflows": []}


@pytest.mark.asyncio
async def test_upsert_creates_workflow() -> None:
    client = _client()
    payload = {
        "name": "alpha",
        "definition": _trivial_definition(),
        "schedule_seconds": None,
        "is_active": False,
    }
    resp = client.put("/api/workflows", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "alpha"
    assert body["definition"]["nodes"][0]["id"] == "r"
    assert body["is_active"] is False

    listed = client.get("/api/workflows").json()
    assert len(listed["workflows"]) == 1


@pytest.mark.asyncio
async def test_upsert_replaces_existing_by_name() -> None:
    client = _client()
    base = {
        "name": "beta",
        "definition": _trivial_definition(),
        "schedule_seconds": 60,
        "is_active": False,
    }
    client.put("/api/workflows", json=base)
    base2 = {**base, "schedule_seconds": 120}
    resp = client.put("/api/workflows", json=base2)
    assert resp.status_code == 200
    assert resp.json()["schedule_seconds"] == 120

    listed = client.get("/api/workflows").json()
    assert len(listed["workflows"]) == 1
    assert listed["workflows"][0]["schedule_seconds"] == 120


@pytest.mark.asyncio
async def test_get_unknown_returns_404() -> None:
    client = _client()
    resp = client.get("/api/workflows/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_removes_workflow() -> None:
    client = _client()
    client.put(
        "/api/workflows",
        json={
            "name": "gamma",
            "definition": _trivial_definition(),
            "schedule_seconds": None,
            "is_active": False,
        },
    )
    resp = client.delete("/api/workflows/gamma")
    assert resp.status_code == 204
    assert client.get("/api/workflows/gamma").status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_returns_404() -> None:
    client = _client()
    resp = client.delete("/api/workflows/missing")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_name_pattern_returns_422() -> None:
    """Pydantic validator should reject names with disallowed characters."""
    client = _client()
    resp = client.put(
        "/api/workflows",
        json={
            "name": "../etc/passwd",
            "definition": _trivial_definition(),
            "schedule_seconds": None,
            "is_active": False,
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Run / enable / disable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_returns_succeeded_payload_for_trivial_graph() -> None:
    client = _client()
    client.put(
        "/api/workflows",
        json={
            "name": "runnable",
            "definition": _trivial_definition(),
            "schedule_seconds": None,
            "is_active": False,
        },
    )
    resp = client.post("/api/workflows/runnable/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] is True
    assert len(body["nodes"]) == 1
    assert body["nodes"][0]["node_type"] == "risk-check"


@pytest.mark.asyncio
async def test_run_unknown_returns_404() -> None:
    client = _client()
    resp = client.post("/api/workflows/missing/run")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_enable_disable_round_trip_toggles_is_active() -> None:
    client = _client()
    client.put(
        "/api/workflows",
        json={
            "name": "toggle",
            "definition": _trivial_definition(),
            "schedule_seconds": 120,
            "is_active": False,
        },
    )

    enabled = client.post("/api/workflows/toggle/enable")
    assert enabled.status_code == 200
    assert enabled.json()["is_active"] is True

    disabled = client.post("/api/workflows/toggle/disable")
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False


@pytest.mark.asyncio
async def test_enable_unknown_returns_404() -> None:
    client = _client()
    resp = client.post("/api/workflows/ghost/enable")
    assert resp.status_code == 404
