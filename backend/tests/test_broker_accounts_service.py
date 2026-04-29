"""Service- and router-level tests for the BrokerAccount CRUD surface.

Mirrors the in-memory SQLite fixture pattern from `test_journal_service.py`.
"""
from __future__ import annotations

import pytest

from app.database import AsyncSessionLocal


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so BrokerAccount rows don't leak."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "broker_accounts.db"
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


# ---------------------------------------------------------------------------
# Create + read round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_then_get_round_trip() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        created = await broker_accounts_service.create_account(
            session,
            broker="Alpaca",
            account_id="ACC-123",
            alias="Primary",
            tier="TIER_1",
        )
        assert created["id"] > 0
        # Broker is lowercased.
        assert created["broker"] == "alpaca"
        assert created["account_id"] == "ACC-123"
        assert created["alias"] == "Primary"
        assert created["tier"] == "TIER_1"
        assert created["is_active"] is True
        assert created["created_at"] is not None
        assert created["updated_at"] is not None

        fetched = await broker_accounts_service.get_account(session, created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["broker"] == "alpaca"


@pytest.mark.asyncio
async def test_get_missing_returns_none() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        assert await broker_accounts_service.get_account(session, 999_999) is None


# ---------------------------------------------------------------------------
# Duplicate (broker, account_id) raises ValueError (DB constraint)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_broker_account_id_raises() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="ACC-1"
        )
        # Same broker (case-insensitive) + same account id -> ValueError.
        with pytest.raises(ValueError):
            await broker_accounts_service.create_account(
                session, broker="ALPACA", account_id="ACC-1"
            )

        # Different account id is fine.
        ok = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="ACC-2"
        )
        assert ok["account_id"] == "ACC-2"


# ---------------------------------------------------------------------------
# Invalid tier rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invalid_tier_raises() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await broker_accounts_service.create_account(
                session, broker="alpaca", account_id="X", tier="TIER_99"
            )


@pytest.mark.asyncio
async def test_update_tier_invalid_raises() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="X"
        )
        with pytest.raises(ValueError):
            await broker_accounts_service.update_tier(session, row["id"], "BOGUS")


# ---------------------------------------------------------------------------
# update_tier persists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_tier_persists() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="ibkr", account_id="U1234567", tier="TIER_2"
        )
        updated = await broker_accounts_service.update_tier(
            session, row["id"], "TIER_1"
        )
        assert updated is not None
        assert updated["tier"] == "TIER_1"

        # Round-trip through the DB.
        fresh = await broker_accounts_service.get_account(session, row["id"])
        assert fresh["tier"] == "TIER_1"

        # Missing row -> None.
        assert await broker_accounts_service.update_tier(
            session, 999_999, "TIER_3"
        ) is None


# ---------------------------------------------------------------------------
# update_alias persists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_alias_persists_and_trims() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="A1", alias="Old"
        )
        updated = await broker_accounts_service.update_alias(
            session, row["id"], "  New name  "
        )
        assert updated is not None
        assert updated["alias"] == "New name"

        fresh = await broker_accounts_service.get_account(session, row["id"])
        assert fresh["alias"] == "New name"

        # Missing row -> None.
        assert await broker_accounts_service.update_alias(
            session, 999_999, "x"
        ) is None


# ---------------------------------------------------------------------------
# set_active toggles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_active_toggles() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="A1"
        )
        assert row["is_active"] is True

        deactivated = await broker_accounts_service.set_active(
            session, row["id"], is_active=False
        )
        assert deactivated["is_active"] is False

        reactivated = await broker_accounts_service.set_active(
            session, row["id"], is_active=True
        )
        assert reactivated["is_active"] is True

        # Missing row -> None.
        assert await broker_accounts_service.set_active(
            session, 999_999, is_active=False
        ) is None


# ---------------------------------------------------------------------------
# delete removes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_removes_and_returns_bool() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="A1"
        )
        assert await broker_accounts_service.delete_account(session, row["id"]) is True
        assert await broker_accounts_service.get_account(session, row["id"]) is None
        # Second delete: gone.
        assert await broker_accounts_service.delete_account(session, row["id"]) is False


# ---------------------------------------------------------------------------
# list filter by only_active
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filter_by_only_active() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        a = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="A1"
        )
        b = await broker_accounts_service.create_account(
            session, broker="alpaca", account_id="A2"
        )
        await broker_accounts_service.set_active(session, b["id"], is_active=False)

        all_rows = await broker_accounts_service.list_accounts(session)
        assert {r["id"] for r in all_rows} == {a["id"], b["id"]}

        active_only = await broker_accounts_service.list_accounts(
            session, only_active=True
        )
        assert [r["id"] for r in active_only] == [a["id"]]


# ---------------------------------------------------------------------------
# Empty broker / account_id rejected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_broker_rejected() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await broker_accounts_service.create_account(
                session, broker="   ", account_id="A1"
            )


@pytest.mark.asyncio
async def test_empty_account_id_rejected() -> None:
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await broker_accounts_service.create_account(
                session, broker="alpaca", account_id="   "
            )


# ---------------------------------------------------------------------------
# Router-level smoke: POST then GET list
# ---------------------------------------------------------------------------


def test_router_post_then_list(client) -> None:
    create_resp = client.post(
        "/api/broker-accounts",
        json={
            "broker": "alpaca",
            "account_id": "ACC-router-1",
            "alias": "router primary",
            "tier": "TIER_1",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["broker"] == "alpaca"
    assert created["account_id"] == "ACC-router-1"
    assert created["tier"] == "TIER_1"

    list_resp = client.get("/api/broker-accounts")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    ids = {item["id"] for item in payload["items"]}
    assert created["id"] in ids
