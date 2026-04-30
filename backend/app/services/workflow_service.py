"""CRUD + run-once service for the Workflow table (Phase 5.6).

Mirrors ``workspace_service.py``:
- ``definition_json`` is a TEXT blob; this layer encodes/decodes via
  ``json.dumps`` / ``json.loads`` so callers work with plain dicts.
- Upsert by name: PUT replaces the entire definition + schedule fields
  if a row with the same name exists, else inserts a new row.

Plus three workflow-specific operations:
- ``run_workflow_by_name`` — pull the row, hand the definition to the
  pure engine in ``core.workflow``. Returns a wire-shaped dict.
- ``enable_workflow`` / ``disable_workflow`` — toggle ``is_active`` AND
  register/unregister a job on the application APScheduler so a
  schedule starts/stops in lockstep with the flag.

MVP NOTE: ``_make_default_fetcher`` returns a deterministic synthetic
price series so tests are reproducible and the engine works without a
Polygon key. Real wiring to ``polygon_service`` is a follow-up — see
the TODO inside the function.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import scheduler as app_scheduler
from app.db.tables import Workflow
from core.indicators import compute_indicator
from core.workflow import NodeResult, WorkflowRunResult, execute_workflow

logger = logging.getLogger(__name__)


# --- Serialisation -------------------------------------------------------

def _serialize(row: Workflow) -> dict[str, Any]:
    """Build a dict shaped for ``WorkflowView``."""
    try:
        definition = json.loads(row.definition_json) if row.definition_json else {}
    except json.JSONDecodeError:
        # Defensive: a corrupt blob shouldn't 500 the whole list endpoint.
        definition = {}
    return {
        "id": row.id,
        "name": row.name,
        "definition": definition,
        "schedule_seconds": row.schedule_seconds,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# --- CRUD ----------------------------------------------------------------

async def list_workflows(session: AsyncSession) -> list[dict[str, Any]]:
    """Return all saved workflows ordered by name (stable for the UI)."""
    stmt = select(Workflow).order_by(Workflow.name)
    result = await session.execute(stmt)
    return [_serialize(row) for row in result.scalars().all()]


async def get_workflow(
    session: AsyncSession, name: str
) -> dict[str, Any] | None:
    stmt = select(Workflow).where(Workflow.name == name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    return _serialize(row) if row is not None else None


async def upsert_workflow(
    session: AsyncSession,
    *,
    name: str,
    definition: dict[str, Any],
    schedule_seconds: int | None,
    is_active: bool,
) -> dict[str, Any]:
    """INSERT … ON CONFLICT(name) DO UPDATE for idempotent PUTs."""
    encoded = json.dumps(definition)
    now = datetime.now(timezone.utc)

    stmt = sqlite_insert(Workflow).values(
        name=name,
        definition_json=encoded,
        schedule_seconds=schedule_seconds,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Workflow.name],
        set_={
            "definition_json": encoded,
            "schedule_seconds": schedule_seconds,
            "is_active": is_active,
            "updated_at": now,
        },
    )
    await session.execute(stmt)
    await session.commit()

    fetch = await session.execute(
        select(Workflow).where(Workflow.name == name)
    )
    row = fetch.scalars().one()
    return _serialize(row)


async def delete_workflow(session: AsyncSession, name: str) -> bool:
    """Delete by name. Also unregisters any matching scheduler job."""
    stmt = select(Workflow).where(Workflow.name == name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    _safely_remove_job(_job_id_for(name))
    return True


# --- Engine wiring -------------------------------------------------------

def _make_default_fetcher():
    """Return a real OHLC fetcher backed by chart_service (yfinance).

    The fetcher returns the CLOSE-ONLY series for the requested lookback
    so detectors that only care about price levels keep working as
    before. If the live fetch fails (rate-limit, no symbol, …) we fall
    back to the deterministic ramp so a single bad symbol doesn't stop
    a multi-symbol workflow run.
    """
    from app.services import chart_service

    async def _fetch(ticker: str, lookback_days: int) -> list[float]:
        # Pick the smallest yfinance period that covers the lookback.
        if lookback_days <= 5:
            range_name = "5d"
        elif lookback_days <= 22:
            range_name = "1mo"
        elif lookback_days <= 66:
            range_name = "3mo"
        elif lookback_days <= 132:
            range_name = "6mo"
        else:
            range_name = "1y"

        try:
            chart = await chart_service.get_symbol_chart(ticker, range_name=range_name)
            points = list((chart or {}).get("points") or [])
            closes = [
                float(p.get("close") or p.get("price") or 0.0)
                for p in points
                if (p.get("close") or p.get("price"))
            ]
            if closes:
                return closes[-lookback_days:] if len(closes) > lookback_days else closes
        except Exception:
            logger.exception("chart fetch failed for %s; falling back to synthetic", ticker)

        # Deterministic fallback so tests + dry runs still produce something.
        seed = sum(ord(c) for c in ticker) % 17
        return [100.0 + seed + i * 0.1 for i in range(lookback_days)]

    return _fetch


def _default_indicator(name: str, period: int, prices: list[float]) -> list[float | None]:
    """Adapter over ``core.indicators.compute_indicator``.

    The engine calls us with positional ``(name, period, prices)``; the
    underlying function returns ``dict[str, list]`` because some
    indicators (MACD, BBANDS) emit several series. We pick the
    canonical series so the engine sees a flat ``list[float | None]``:
    - sma/ema/rsi → ``value``
    - macd        → ``macd``
    - bbands      → ``middle``
    """
    series_map = compute_indicator(name, prices, params={"period": period})
    if "value" in series_map:
        return series_map["value"]
    if name == "macd":
        return series_map["macd"]
    if name == "bbands":
        return series_map["middle"]
    # Fall back to the first series to remain forward-compatible.
    return next(iter(series_map.values()))


async def _default_paper_order(payload: dict[str, Any]) -> dict[str, Any]:
    """Real Alpaca paper-order dispatcher with safe fallback.

    Workflow node payloads carry ``side`` and ``qty`` (and ``paper:True``
    by convention). We always force ``paper`` mode here regardless of
    the node's flag — production live trading from a workflow is out of
    scope. If Alpaca isn't configured / fails, we log the intent and
    return ``{"accepted": True, "broker": "noop", "reason": ...}`` so
    the workflow doesn't break.
    """
    side = str(payload.get("side") or "").lower()
    if side not in {"buy", "sell"}:
        return {"accepted": False, "broker": "noop", "reason": f"invalid side: {side!r}"}

    symbol = str(payload.get("symbol") or "").upper()
    if not symbol:
        # Workflow order nodes may not carry a symbol; without one we
        # can't dispatch — keep a structured no-op result.
        logger.info("workflow paper-order without symbol: %s", payload)
        return {"accepted": True, "broker": "noop", "reason": "no symbol in node payload"}

    qty = payload.get("qty")
    notional = payload.get("notional")
    try:
        from app.services import alpaca_service
        result = await alpaca_service.submit_order(
            symbol,
            side,
            qty=float(qty) if qty is not None else None,
            notional=float(notional) if notional is not None else None,
        )
        return {"accepted": True, "broker": "alpaca-paper", "order": result}
    except Exception as exc:
        logger.warning("workflow paper-order failed for %s/%s: %s", symbol, side, exc)
        return {"accepted": True, "broker": "noop", "reason": str(exc)}


def _to_view(result: WorkflowRunResult) -> dict[str, Any]:
    """Shape a ``WorkflowRunResult`` into a dict for ``WorkflowRunView``."""
    return {
        "succeeded": result.succeeded,
        "duration_ms": result.duration_ms,
        "nodes": [_node_to_dict(n) for n in result.nodes],
        "final_output": result.final_output,
    }


def _node_to_dict(node: NodeResult) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "node_type": node.node_type,
        "output": node.output,
        "error": node.error,
    }


async def run_workflow_by_name(
    session: AsyncSession, name: str
) -> dict[str, Any] | None:
    """Look up the workflow, run the engine once, return wire-shape dict.

    Returns None when the workflow does not exist so the router can
    return 404. Engine errors are surfaced as ``succeeded=False`` in the
    payload, never as exceptions.
    """
    row = await get_workflow(session, name)
    if row is None:
        return None
    result = await execute_workflow(
        row["definition"],
        fetcher=_make_default_fetcher(),
        indicator_fn=_default_indicator,
        paper_order_fn=_default_paper_order,
    )
    return _to_view(result)


# --- Scheduler registration ---------------------------------------------

def _job_id_for(name: str) -> str:
    return f"workflow_{name}"


def _safely_remove_job(job_id: str) -> None:
    """Remove a scheduler job, swallowing the not-found path.

    The scheduler may not have been started yet (e.g., in tests that
    construct TestClient without lifespan), in which case this is a
    no-op.
    """
    sched = app_scheduler.get_scheduler()
    if sched is None:
        return
    try:
        sched.remove_job(job_id)
    except Exception:  # noqa: BLE001 — APS raises JobLookupError; treat all as no-op
        logger.debug("remove_job(%s) skipped (not registered)", job_id)


def _make_workflow_runner(name: str):
    """Build the no-args coroutine APS expects for a registered job."""

    async def _run() -> None:
        try:
            from app.db.engine import AsyncSessionLocal as _SessionLocal
            async with _SessionLocal() as inner:
                await run_workflow_by_name(inner, name)
        except Exception:  # noqa: BLE001 — never let one workflow's failure kill the scheduler
            logger.exception("scheduled workflow %s failed", name)

    return _run


def _register_job_for(name: str, schedule_seconds: int) -> None:
    sched = app_scheduler.get_scheduler()
    if sched is None:
        # Scheduler not started yet (e.g., during tests). Skip silently;
        # the job will be (re)registered on next lifespan boot.
        logger.debug("scheduler not started; deferring workflow_%s", name)
        return
    app_scheduler.register_job(
        _job_id_for(name),
        _make_workflow_runner(name),
        IntervalTrigger(seconds=schedule_seconds),
    )


async def register_workflow_jobs(session: AsyncSession) -> int:
    """Register every active+scheduled workflow on the app scheduler.

    Called once during lifespan after ``register_default_jobs()``.
    Returns the count registered (handy for tests + ops logging).
    """
    stmt = select(Workflow).where(
        Workflow.is_active.is_(True),
        Workflow.schedule_seconds.is_not(None),
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    for row in rows:
        # Type narrowing — the WHERE clause already excludes None, but
        # mypy/static checkers don't see that at runtime.
        if row.schedule_seconds is None:
            continue
        _register_job_for(row.name, row.schedule_seconds)
    return len(rows)


async def enable_workflow(
    session: AsyncSession, name: str
) -> dict[str, Any] | None:
    """Mark a workflow active and register its scheduled job."""
    stmt = select(Workflow).where(Workflow.name == name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    row.is_active = True
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    if row.schedule_seconds is not None:
        _register_job_for(row.name, row.schedule_seconds)
    return _serialize(row)


async def disable_workflow(
    session: AsyncSession, name: str
) -> dict[str, Any] | None:
    """Mark a workflow inactive and unregister its scheduled job."""
    stmt = select(Workflow).where(Workflow.name == name)
    result = await session.execute(stmt)
    row = result.scalars().first()
    if row is None:
        return None
    row.is_active = False
    row.updated_at = datetime.now(timezone.utc)
    await session.commit()
    _safely_remove_job(_job_id_for(name))
    return _serialize(row)
