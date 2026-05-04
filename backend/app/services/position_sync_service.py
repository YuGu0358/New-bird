"""Periodic broker-position snapshot writer.

Iterates active `BrokerAccount` rows where `broker == 'ibkr'`, fetches
positions via `ibkr_service.list_positions()`, and writes one
`PositionSnapshot` row per (account, symbol). The scheduled-jobs
registry wires this to a 5-minute interval.

Degrade gracefully: any per-account fetch error is logged and skipped;
the next scheduled tick will retry. The function never raises to the
APScheduler runner.

Multi-account note: today's `ibkr_service` uses a single
`IBKR_ACCOUNT_ID` setting and connects to one IB Gateway session at a
time. We attribute every fetched position to the BrokerAccount whose
`account_id` matches `IBKR_ACCOUNT_ID`. If the user has multiple IBKR
BrokerAccount rows but only one is set as the active session in
settings, only that one gets snapshots — multi-session orchestration is
a follow-up task (Phase 2 polish).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import BrokerAccount, PositionSnapshot
from app.services import ibkr_service

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _active_ibkr_accounts(session: AsyncSession) -> list[BrokerAccount]:
    statement = select(BrokerAccount).where(
        BrokerAccount.broker == "ibkr",
        BrokerAccount.is_active.is_(True),
    )
    result = await session.execute(statement)
    return list(result.scalars().all())


async def _ibkr_session_account_id() -> str | None:
    """Read the IBKR account id from settings — the active session target."""
    raw = runtime_settings.get_setting("IBKR_ACCOUNT_ID", "") or ""
    return raw.strip() or None


def _serialize(row: PositionSnapshot) -> dict[str, Any]:
    return {
        "id": row.id,
        "broker_account_id": row.broker_account_id,
        "symbol": row.symbol,
        "snapshot_at": row.snapshot_at,
        "qty": row.qty,
        "avg_cost": row.avg_cost,
        "market_value": row.market_value,
        "current_price": row.current_price,
        "unrealized_pl": row.unrealized_pl,
        "side": row.side,
    }


async def snapshot_once(
    session: AsyncSession | None = None,
) -> int:
    """Run one snapshot pass. Returns the number of rows written.

    Designed to be called from APScheduler (no args, returns a count).
    The optional `session` makes unit testing trivial — production
    callers leave it None and we open one via `AsyncSessionLocal`.
    """
    own_session = session is None
    if own_session:
        async with AsyncSessionLocal() as new_session:
            return await snapshot_once(session=new_session)
    assert session is not None  # narrowing for type-checkers

    target_account_id = await _ibkr_session_account_id()
    if target_account_id is None:
        logger.debug(
            "position_sync: IBKR_ACCOUNT_ID unset; skipping snapshot pass"
        )
        return 0

    accounts = await _active_ibkr_accounts(session)
    matching = [a for a in accounts if a.account_id == target_account_id]
    if not matching:
        logger.debug(
            "position_sync: no active BrokerAccount row matches IBKR_ACCOUNT_ID=%r",
            target_account_id,
        )
        return 0

    # Fetch ONCE per pass — the IBKR session is single-account at present.
    try:
        positions = await ibkr_service.list_positions()
    except Exception:  # noqa: BLE001
        logger.exception("position_sync: ibkr_service.list_positions failed")
        return 0

    if not positions:
        return 0

    written = 0
    now = _now()
    for account in matching:
        for pos in positions:
            symbol = str(pos.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            try:
                qty = float(pos.get("qty") or 0.0)
            except (TypeError, ValueError):
                continue
            row = PositionSnapshot(
                broker_account_id=account.id,
                symbol=symbol,
                snapshot_at=now,
                qty=qty,
                avg_cost=_safe_float(pos.get("avg_entry_price")),
                market_value=_safe_float(pos.get("market_value")),
                current_price=_safe_float(pos.get("current_price")),
                unrealized_pl=_safe_float(pos.get("unrealized_pl")),
                side=str(pos.get("side") or ("long" if qty >= 0 else "short")),
            )
            session.add(row)
            written += 1
    if written:
        await session.commit()
    return written


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


async def list_snapshots(
    session: AsyncSession,
    *,
    broker_account_id: int | None = None,
    symbol: str | None = None,
    since: datetime | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Read snapshots in descending snapshot_at order. limit clamped to [1,1000]."""
    # Use `if limit is None` rather than `or 200` so an explicit limit=0
    # clamps to 1 (the floor) rather than falsy-coercing to the default.
    raw = 200 if limit is None else int(limit)
    capped = max(1, min(raw, 1000))
    statement = select(PositionSnapshot).order_by(
        PositionSnapshot.snapshot_at.desc()
    )
    if broker_account_id is not None:
        statement = statement.where(
            PositionSnapshot.broker_account_id == broker_account_id
        )
    if symbol:
        statement = statement.where(
            PositionSnapshot.symbol == symbol.strip().upper()
        )
    if since is not None:
        statement = statement.where(PositionSnapshot.snapshot_at >= since)
    statement = statement.limit(capped)
    result = await session.execute(statement)
    return [_serialize(row) for row in result.scalars().all()]
