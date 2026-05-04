"""Service- and router-level tests for the PositionOverride CRUD surface.

Mirrors the in-memory SQLite fixture pattern from
`test_broker_accounts_service.py` — overrides reference BrokerAccount
rows, so every test has to seed an account first.
"""
from __future__ import annotations

import math

import pytest

from app.database import AsyncSessionLocal


@pytest.fixture(autouse=True)
async def _isolate_db(monkeypatch, tmp_path):
    """Fresh tmp DB per test so PositionOverride / BrokerAccount rows don't leak."""
    import importlib

    engine_module = importlib.import_module("app.db.engine")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    original_engine = engine_module.engine
    db_path = tmp_path / "position_overrides.db"
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


async def _seed_account(broker: str = "alpaca", account_id: str = "ACC-1") -> int:
    """Helper: create a BrokerAccount row and return its primary key."""
    from app.services import broker_accounts_service

    async with AsyncSessionLocal() as session:
        row = await broker_accounts_service.create_account(
            session, broker=broker, account_id=account_id
        )
        return int(row["id"])


# ---------------------------------------------------------------------------
# 1. Set override against a real BrokerAccount -> round-trip via list + get
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_round_trip() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        created = await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="AAPL",
            stop_price=180.5,
            take_profit_price=210.0,
            notes="watch earnings",
            tier_override="TIER_1",
        )
        assert created["broker_account_id"] == pk
        assert created["ticker"] == "AAPL"
        assert created["stop_price"] == 180.5
        assert created["take_profit_price"] == 210.0
        assert created["notes"] == "watch earnings"
        assert created["tier_override"] == "TIER_1"
        assert created["created_at"] is not None
        assert created["updated_at"] is not None

        fetched = await svc.get_override(session, pk, "AAPL")
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["stop_price"] == 180.5

        listed = await svc.list_overrides(session)
        assert any(r["id"] == created["id"] for r in listed)


# ---------------------------------------------------------------------------
# 2. Unknown broker_account_id -> ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_unknown_broker_account_raises() -> None:
    from app.services import position_overrides_service as svc

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await svc.set_override(
                session, broker_account_id=99999, ticker="AAPL"
            )


# ---------------------------------------------------------------------------
# 3. Negative stop_price -> ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_negative_stop_price_raises() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await svc.set_override(
                session,
                broker_account_id=pk,
                ticker="AAPL",
                stop_price=-1.0,
            )


# ---------------------------------------------------------------------------
# 4. NaN stop_price -> ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_nan_stop_price_raises() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await svc.set_override(
                session,
                broker_account_id=pk,
                ticker="AAPL",
                stop_price=float("nan"),
            )


# ---------------------------------------------------------------------------
# 5. Invalid tier_override -> ValueError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_invalid_tier_raises() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await svc.set_override(
                session,
                broker_account_id=pk,
                ticker="AAPL",
                tier_override="TIER_99",
            )


# ---------------------------------------------------------------------------
# 6. tier_override=None clears the field on existing row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_override_tier_override_none_clears() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="AAPL",
            tier_override="TIER_1",
        )
        cleared = await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="AAPL",
            tier_override=None,
        )
        assert cleared["tier_override"] is None

        fresh = await svc.get_override(session, pk, "AAPL")
        assert fresh is not None
        assert fresh["tier_override"] is None


# ---------------------------------------------------------------------------
# 7. Update via second PUT replaces fields atomically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_second_set_replaces_fields() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        first = await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="AAPL",
            stop_price=100.0,
            take_profit_price=200.0,
            notes="first",
            tier_override="TIER_1",
        )
        second = await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="AAPL",
            stop_price=120.0,
            take_profit_price=220.0,
            notes="second",
            tier_override="TIER_2",
        )
        # Same row id (upsert) but fields replaced.
        assert second["id"] == first["id"]
        assert second["stop_price"] == 120.0
        assert second["take_profit_price"] == 220.0
        assert second["notes"] == "second"
        assert second["tier_override"] == "TIER_2"


# ---------------------------------------------------------------------------
# 8. Delete returns True when present, False when missing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_returns_bool() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        await svc.set_override(
            session, broker_account_id=pk, ticker="AAPL", stop_price=100.0
        )
        assert await svc.delete_override(session, pk, "AAPL") is True
        assert await svc.delete_override(session, pk, "AAPL") is False
        assert await svc.get_override(session, pk, "AAPL") is None


# ---------------------------------------------------------------------------
# 9. List filtered by broker_account_id only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filter_by_broker_account_id() -> None:
    from app.services import position_overrides_service as svc

    pk_a = await _seed_account(account_id="ACC-A")
    pk_b = await _seed_account(account_id="ACC-B")

    async with AsyncSessionLocal() as session:
        await svc.set_override(
            session, broker_account_id=pk_a, ticker="AAPL", stop_price=1.0
        )
        await svc.set_override(
            session, broker_account_id=pk_a, ticker="MSFT", stop_price=1.0
        )
        await svc.set_override(
            session, broker_account_id=pk_b, ticker="AAPL", stop_price=1.0
        )

        rows_a = await svc.list_overrides(session, broker_account_id=pk_a)
        assert {r["ticker"] for r in rows_a} == {"AAPL", "MSFT"}
        assert all(r["broker_account_id"] == pk_a for r in rows_a)

        rows_b = await svc.list_overrides(session, broker_account_id=pk_b)
        assert {r["ticker"] for r in rows_b} == {"AAPL"}


# ---------------------------------------------------------------------------
# 10. List filtered by ticker only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_filter_by_ticker_only() -> None:
    from app.services import position_overrides_service as svc

    pk_a = await _seed_account(account_id="ACC-A")
    pk_b = await _seed_account(account_id="ACC-B")

    async with AsyncSessionLocal() as session:
        await svc.set_override(
            session, broker_account_id=pk_a, ticker="AAPL", stop_price=1.0
        )
        await svc.set_override(
            session, broker_account_id=pk_b, ticker="AAPL", stop_price=1.0
        )
        await svc.set_override(
            session, broker_account_id=pk_a, ticker="MSFT", stop_price=1.0
        )

        # Filter is normalized to uppercase too — pass lowercase to verify.
        rows_aapl = await svc.list_overrides(session, ticker="aapl")
        assert {r["broker_account_id"] for r in rows_aapl} == {pk_a, pk_b}
        assert all(r["ticker"] == "AAPL" for r in rows_aapl)


# ---------------------------------------------------------------------------
# 11. Ticker normalization: PUT "aapl" then GET "AAPL" returns the row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticker_normalized_to_uppercase() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        created = await svc.set_override(
            session,
            broker_account_id=pk,
            ticker="aapl",
            stop_price=10.0,
        )
        assert created["ticker"] == "AAPL"

        fetched = await svc.get_override(session, pk, "AAPL")
        assert fetched is not None
        assert fetched["id"] == created["id"]

        # Lower-case lookups also normalize.
        again = await svc.get_override(session, pk, "aapl")
        assert again is not None
        assert again["id"] == created["id"]


# ---------------------------------------------------------------------------
# Bonus: NaN take_profit_price also rejected (defensive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nan_take_profit_price_rejected() -> None:
    from app.services import position_overrides_service as svc

    pk = await _seed_account()

    async with AsyncSessionLocal() as session:
        with pytest.raises(ValueError):
            await svc.set_override(
                session,
                broker_account_id=pk,
                ticker="AAPL",
                take_profit_price=math.inf,
            )


# ---------------------------------------------------------------------------
# Router-level smoke: BrokerAccount POST -> override PUT -> GET roundtrip
# ---------------------------------------------------------------------------


def test_router_put_then_get_round_trip(client) -> None:
    create_resp = client.post(
        "/api/broker-accounts",
        json={
            "broker": "alpaca",
            "account_id": "ACC-router-overrides",
            "alias": "rtr",
            "tier": "TIER_1",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    account_pk = create_resp.json()["id"]

    put_resp = client.put(
        "/api/portfolio/overrides",
        json={
            "broker_account_id": account_pk,
            "ticker": "tsla",
            "stop_price": 150.0,
            "take_profit_price": 250.0,
            "notes": "router",
            "tier_override": "TIER_2",
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    payload = put_resp.json()
    assert payload["broker_account_id"] == account_pk
    assert payload["ticker"] == "TSLA"  # normalized
    assert payload["stop_price"] == 150.0
    assert payload["take_profit_price"] == 250.0
    assert payload["notes"] == "router"
    assert payload["tier_override"] == "TIER_2"

    get_resp = client.get(f"/api/portfolio/overrides/{account_pk}/TSLA")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["id"] == payload["id"]

    # Lower-case ticker via path param also resolves.
    get_resp2 = client.get(f"/api/portfolio/overrides/{account_pk}/tsla")
    assert get_resp2.status_code == 200
    assert get_resp2.json()["id"] == payload["id"]

    # List with filter.
    list_resp = client.get(
        "/api/portfolio/overrides",
        params={"broker_account_id": account_pk},
    )
    assert list_resp.status_code == 200
    assert any(
        item["ticker"] == "TSLA" for item in list_resp.json()["items"]
    )

    # Bad PUT (unknown broker_account_id) -> 400.
    bad_resp = client.put(
        "/api/portfolio/overrides",
        json={
            "broker_account_id": 99999,
            "ticker": "AAPL",
            "stop_price": 1.0,
        },
    )
    assert bad_resp.status_code == 400

    # Delete -> 204, second delete -> 404.
    del_resp = client.delete(f"/api/portfolio/overrides/{account_pk}/TSLA")
    assert del_resp.status_code == 204
    del_resp2 = client.delete(f"/api/portfolio/overrides/{account_pk}/TSLA")
    assert del_resp2.status_code == 404
