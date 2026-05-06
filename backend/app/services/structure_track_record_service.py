"""Persist & evaluate options-structure-read theses.

Three responsibilities:
1. ``capture_snapshot(ticker, horizon_days)`` — call get_structure_read(),
   freeze the inputs needed for outcome scoring, persist one row per
   (capture_date, ticker, horizon_days). Idempotent on the composite key.
2. ``evaluate_pending(...)`` — walk pending snapshots whose
   horizon_end_date has arrived, fetch underlying OHLC for the window,
   run ``structure_outcome.evaluate_outcome``, write the result back.
3. ``aggregate_track_record(...)`` — group evaluated snapshots by
   pattern and report hit-rate / sample count.

OHLC is sourced from yfinance via ``chart_service.get_symbol_chart`` — no
new external dependency.
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.engine import AsyncSessionLocal
from app.db.tables import OptionsStructureSnapshot
from app.services import chart_service, options_chain_service
from core.options_chain.structure_outcome import (
    HorizonBar,
    OUTCOME_HIT,
    OUTCOME_MISS,
    OUTCOME_NO_EDGE,
    OUTCOME_UNEVALUABLE,
    evaluate_outcome,
)

logger = logging.getLogger(__name__)


DEFAULT_HORIZON_DAYS = 5
SUPPORTED_HORIZONS = (5, 10)
_OUTCOME_PENDING = "pending"


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


async def capture_snapshot(
    ticker: str,
    *,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
) -> dict[str, Any] | None:
    """Capture a single snapshot. Returns the persisted row as a dict, or
    None if the chain is empty / structure-read returned None.

    Re-running on the same UTC day for the same (ticker, horizon) is a
    no-op (returns the existing row) thanks to SQLite ON CONFLICT DO
    NOTHING semantics — the first read of the day is the canonical one.
    """
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")

    payload = await options_chain_service.get_structure_read(ticker)
    if payload is None:
        return None

    inputs = payload.get("inputs_used") or {}
    spot = float(inputs.get("spot") or 0.0)
    if spot <= 0:
        return None

    capture_d = _today_utc()
    horizon_end = capture_d + timedelta(days=horizon_days)

    row_values = {
        "capture_date": capture_d,
        "ticker": ticker.upper(),
        "horizon_days": int(horizon_days),
        "captured_at": datetime.now(timezone.utc),
        "pattern": payload["pattern"],
        "winning_player": payload["winning_player"],
        "confidence": int(payload.get("confidence") or 0),
        "signals_fired_json": json.dumps(payload.get("signals_fired") or []),
        "spot_at_capture": spot,
        "call_wall": _opt_float(inputs.get("call_wall")),
        "put_wall": _opt_float(inputs.get("put_wall")),
        "max_pain": _opt_float(inputs.get("max_pain")),
        "expected_move_pct": _opt_float(inputs.get("expected_move_pct")),
        "horizon_end_date": horizon_end,
        "outcome_status": _OUTCOME_PENDING,
    }

    async with AsyncSessionLocal() as session:
        stmt = sqlite_insert(OptionsStructureSnapshot).values(**row_values)
        # Idempotent on the composite PK — first capture of the day wins.
        stmt = stmt.on_conflict_do_nothing(
            index_elements=["capture_date", "ticker", "horizon_days"]
        )
        await session.execute(stmt)
        await session.commit()

        existing = await session.execute(
            select(OptionsStructureSnapshot).where(
                OptionsStructureSnapshot.capture_date == capture_d,
                OptionsStructureSnapshot.ticker == ticker.upper(),
                OptionsStructureSnapshot.horizon_days == int(horizon_days),
            )
        )
        row = existing.scalar_one_or_none()

    if row is None:
        return None
    return _row_to_dict(row)


def _opt_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def evaluate_pending(*, max_rows: int = 200) -> dict[str, int]:
    """Evaluate snapshots whose horizon has arrived. Returns counters."""
    today_d = _today_utc()
    counters: dict[str, int] = {"considered": 0, "evaluated": 0, "skipped": 0}

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(OptionsStructureSnapshot)
                .where(
                    OptionsStructureSnapshot.outcome_status == _OUTCOME_PENDING,
                    OptionsStructureSnapshot.horizon_end_date <= today_d,
                )
                .order_by(OptionsStructureSnapshot.horizon_end_date)
                .limit(max_rows)
            )
        ).scalars().all()

    counters["considered"] = len(rows)

    for row in rows:
        try:
            bars = await _fetch_window_bars(
                row.ticker,
                start=row.capture_date,
                end=row.horizon_end_date,
            )
        except Exception:
            logger.warning(
                "track-record bar fetch failed for %s %s",
                row.ticker,
                row.capture_date,
                exc_info=True,
            )
            counters["skipped"] += 1
            continue

        if not bars:
            counters["skipped"] += 1
            continue

        outcome = evaluate_outcome(
            pattern=row.pattern,
            spot_at_capture=row.spot_at_capture,
            call_wall=row.call_wall,
            put_wall=row.put_wall,
            expected_move_pct=row.expected_move_pct,
            bars=bars,
        )

        async with AsyncSessionLocal() as session:
            persisted = await session.get(
                OptionsStructureSnapshot,
                (row.capture_date, row.ticker, row.horizon_days),
            )
            if persisted is None:
                counters["skipped"] += 1
                continue
            persisted.outcome_status = outcome.status
            persisted.realized_close = outcome.realized_close
            persisted.realized_high = outcome.realized_high
            persisted.realized_low = outcome.realized_low
            persisted.realized_move_pct = outcome.realized_move_pct
            persisted.outcome_metric_json = json.dumps(outcome.metric)
            persisted.evaluated_at = datetime.now(timezone.utc)
            await session.commit()

        counters["evaluated"] += 1

    return counters


async def _fetch_window_bars(
    ticker: str, *, start: date, end: date
) -> list[HorizonBar]:
    """Bars strictly *after* start, up to and including end. Returns
    HorizonBar list ordered by date."""
    chart = await chart_service.get_symbol_chart(ticker, range_name="3mo")
    points = chart.get("points") or []
    bars: list[HorizonBar] = []
    for p in points:
        ts = p.get("timestamp") or p.get("date")
        if ts is None:
            continue
        try:
            d = _coerce_date(ts)
        except ValueError:
            continue
        if d <= start or d > end:
            continue
        try:
            bars.append(
                HorizonBar(
                    high=float(p["high"]),
                    low=float(p["low"]),
                    close=float(p["close"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return bars


def _coerce_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value)
    # Trim time portion if present (e.g. '2026-05-04T00:00:00').
    return date.fromisoformat(s[:10])


def _row_to_dict(row: OptionsStructureSnapshot) -> dict[str, Any]:
    return {
        "capture_date": row.capture_date.isoformat(),
        "ticker": row.ticker,
        "horizon_days": row.horizon_days,
        "captured_at": row.captured_at.isoformat() if row.captured_at else None,
        "pattern": row.pattern,
        "winning_player": row.winning_player,
        "confidence": row.confidence,
        "signals_fired": json.loads(row.signals_fired_json or "[]"),
        "spot_at_capture": row.spot_at_capture,
        "call_wall": row.call_wall,
        "put_wall": row.put_wall,
        "max_pain": row.max_pain,
        "expected_move_pct": row.expected_move_pct,
        "horizon_end_date": row.horizon_end_date.isoformat(),
        "outcome_status": row.outcome_status,
        "realized_close": row.realized_close,
        "realized_high": row.realized_high,
        "realized_low": row.realized_low,
        "realized_move_pct": row.realized_move_pct,
        "outcome_metric": json.loads(row.outcome_metric_json) if row.outcome_metric_json else None,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
    }


async def list_recent_snapshots(
    *, ticker: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        q = select(OptionsStructureSnapshot)
        if ticker:
            q = q.where(OptionsStructureSnapshot.ticker == ticker.upper())
        q = q.order_by(desc(OptionsStructureSnapshot.capture_date)).limit(
            max(1, min(limit, 1000))
        )
        rows = (await session.execute(q)).scalars().all()
    return [_row_to_dict(r) for r in rows]


async def aggregate_track_record(
    *, horizon_days: int | None = None
) -> dict[str, Any]:
    """Group evaluated snapshots by pattern; report hit-rate per pattern.

    UNCLEAR rows are excluded from rate denominators because they have
    no thesis to test (status=no_edge). Pending and unevaluable rows are
    also excluded from rates but reported in the totals.
    """
    async with AsyncSessionLocal() as session:
        q = select(OptionsStructureSnapshot)
        if horizon_days is not None:
            q = q.where(OptionsStructureSnapshot.horizon_days == int(horizon_days))
        rows = (await session.execute(q)).scalars().all()

    by_pattern: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total": 0,
            "pending": 0,
            "hit": 0,
            "miss": 0,
            "no_edge": 0,
            "unevaluable": 0,
            "confidence_weighted_hits": 0.0,
            "confidence_weighted_evaluated": 0.0,
        }
    )

    for r in rows:
        bucket = by_pattern[r.pattern]
        bucket["total"] += 1
        if r.outcome_status == _OUTCOME_PENDING:
            bucket["pending"] += 1
            continue
        if r.outcome_status == OUTCOME_HIT:
            bucket["hit"] += 1
            bucket["confidence_weighted_hits"] += float(r.confidence or 0)
            bucket["confidence_weighted_evaluated"] += float(r.confidence or 0)
        elif r.outcome_status == OUTCOME_MISS:
            bucket["miss"] += 1
            bucket["confidence_weighted_evaluated"] += float(r.confidence or 0)
        elif r.outcome_status == OUTCOME_NO_EDGE:
            bucket["no_edge"] += 1
        elif r.outcome_status == OUTCOME_UNEVALUABLE:
            bucket["unevaluable"] += 1

    items: list[dict[str, Any]] = []
    for pattern, b in sorted(by_pattern.items()):
        evaluated = b["hit"] + b["miss"]
        hit_rate = (b["hit"] / evaluated) if evaluated > 0 else None
        weighted = b["confidence_weighted_evaluated"]
        weighted_hit_rate = (
            (b["confidence_weighted_hits"] / weighted) if weighted > 0 else None
        )
        items.append(
            {
                "pattern": pattern,
                "total_snapshots": b["total"],
                "evaluated": evaluated,
                "hits": b["hit"],
                "misses": b["miss"],
                "pending": b["pending"],
                "no_edge": b["no_edge"],
                "unevaluable": b["unevaluable"],
                "hit_rate": hit_rate,
                "confidence_weighted_hit_rate": weighted_hit_rate,
            }
        )

    return {
        "horizon_days": horizon_days,
        "items": items,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
