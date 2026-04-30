"""Alpha Arena — leaderboard for AI Council personas.

Two surfaces:
- ``run_arena``: dispatches every selected persona against every supplied
  symbol via :func:`agents_service.analyze` (which actually calls the LLM and
  persists into ``agent_analyses``), then returns the fresh verdicts plus a
  scoreboard derived from past rows.
- ``get_scoreboard``: pure historical view — no fresh LLM calls. Walks the
  ``agent_analyses`` table over a lookback window, computes hypothetical P&L
  for each "buy" verdict by comparing the symbol's close at ``created_at``
  vs. the latest close, and aggregates per persona.

Reuses existing infrastructure only: no new schema, no new dependencies.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AgentAnalysis
from app.services import agents_service, chart_service
from core.agents import list_personas
from core.i18n import DEFAULT_LANG

logger = logging.getLogger(__name__)

# A "hit" is a buy verdict whose hypothetical P&L exceeded this threshold.
HIT_THRESHOLD_PCT: float = 2.0

# Largest grid we'll dispatch — keeps M × N from blowing up the LLM bill.
MAX_SYMBOLS: int = 5

# Default historical window for scoreboard computation.
DEFAULT_LOOKBACK_DAYS: int = 90


def _builtin_persona_ids() -> list[str]:
    return [p.id for p in list_personas()]


def _persona_meta(persona_id: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort (name, style) lookup. Returns (None, None) if unknown."""
    for p in list_personas():
        if p.id == persona_id:
            return p.name, p.style
    return None, None


def _normalize_symbols(symbols: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        if not raw:
            continue
        sym = str(raw).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        cleaned.append(sym)
    return cleaned


async def get_scoreboard(
    session: AsyncSession,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Compute the persona scoreboard from past AgentAnalysis rows."""
    if lookback_days <= 0:
        raise ValueError("lookback_days must be positive")

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    stmt = select(AgentAnalysis).where(AgentAnalysis.created_at >= cutoff)
    rows = (await session.execute(stmt)).scalars().all()

    # Pre-aggregate metadata per persona — even personas with zero rows show up
    # so the UI can render a stable grid.
    persona_buckets: dict[str, dict[str, Any]] = {
        pid: _empty_bucket(pid) for pid in _builtin_persona_ids()
    }

    # Cache chart fetches: each unique symbol is queried at most once.
    latest_cache: dict[str, Optional[float]] = {}
    history_chart: dict[str, list[dict[str, Any]]] = {}

    async def _ensure_chart(symbol: str) -> list[dict[str, Any]]:
        if symbol in history_chart:
            return history_chart[symbol]
        try:
            chart = await chart_service.get_symbol_chart(symbol, range_name="1y")
        except Exception as exc:
            logger.debug("history chart failed for %s: %s", symbol, exc)
            history_chart[symbol] = []
            latest_cache.setdefault(symbol, None)
            return []
        points = list((chart or {}).get("points") or [])
        history_chart[symbol] = points
        if points:
            try:
                latest_cache.setdefault(symbol, float(points[-1].get("close")))
            except (TypeError, ValueError):
                latest_cache.setdefault(symbol, None)
        else:
            latest_cache.setdefault(symbol, None)
        return points

    for row in rows:
        bucket = persona_buckets.setdefault(row.persona_id, _empty_bucket(row.persona_id))
        verdict = (row.verdict or "").lower()
        if verdict == "buy":
            bucket["buy_calls"] += 1
        elif verdict == "sell":
            bucket["sell_calls"] += 1
        else:
            bucket["hold_calls"] += 1

        if verdict != "buy":
            continue

        points = await _ensure_chart(row.symbol)
        if not points:
            continue
        entry_price = _close_on_or_before_points(points, row.created_at)
        latest_price = latest_cache.get(row.symbol)
        if entry_price is None or latest_price is None or entry_price <= 0:
            continue

        pnl_pct = ((latest_price - entry_price) / entry_price) * 100.0
        bucket["pnl_samples"].append(pnl_pct)
        if pnl_pct >= HIT_THRESHOLD_PCT:
            bucket["hits"] += 1

        snapshot = {
            "symbol": row.symbol,
            "pnl_pct": pnl_pct,
            "entry_price": entry_price,
            "current_price": latest_price,
            "created_at": row.created_at,
        }
        if bucket["best_call"] is None or pnl_pct > bucket["best_call"]["pnl_pct"]:
            bucket["best_call"] = snapshot
        if bucket["worst_call"] is None or pnl_pct < bucket["worst_call"]["pnl_pct"]:
            bucket["worst_call"] = snapshot

    scoreboard = [_finalize_bucket(b) for b in persona_buckets.values()]
    scoreboard.sort(key=_score_sort_key, reverse=True)
    return {"scoreboard": scoreboard, "lookback_days": lookback_days}


async def run_arena(
    session: AsyncSession,
    *,
    symbols: list[str],
    persona_ids: Optional[list[str]] = None,
    lang: str = DEFAULT_LANG,
) -> dict[str, Any]:
    """Run all (or selected) personas on each symbol; return verdicts + scoreboard."""
    cleaned_symbols = _normalize_symbols(symbols)
    if not cleaned_symbols:
        raise ValueError("symbols must not be empty")
    if len(cleaned_symbols) > MAX_SYMBOLS:
        raise ValueError(f"At most {MAX_SYMBOLS} symbols per run")

    chosen_ids = list(persona_ids) if persona_ids else _builtin_persona_ids()
    if not chosen_ids:
        raise ValueError("persona_ids must not be empty")

    current: list[dict[str, Any]] = []
    for symbol in cleaned_symbols:
        for pid in chosen_ids:
            try:
                analysis = await agents_service.analyze(
                    session, persona_id=pid, symbol=symbol, lang=lang,
                )
            except KeyError as exc:
                # Bad persona id — surface as ValueError so the router maps to 400.
                raise ValueError(f"Unknown persona id: {pid!r}") from exc
            name, _ = _persona_meta(pid)
            current.append({
                "symbol": symbol,
                "persona_id": pid,
                "persona_name": name,
                "verdict": analysis.get("verdict") or "hold",
                "confidence": float(analysis.get("confidence") or 0.0),
                "reasoning_summary": analysis.get("reasoning_summary"),
                "action_plan": analysis.get("action_plan"),
                "created_at": analysis.get("created_at"),
            })

    board = await get_scoreboard(session)
    return {"current": current, "scoreboard": board["scoreboard"]}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _empty_bucket(persona_id: str) -> dict[str, Any]:
    name, style = _persona_meta(persona_id)
    return {
        "persona_id": persona_id,
        "name": name,
        "style": style,
        "buy_calls": 0,
        "sell_calls": 0,
        "hold_calls": 0,
        "hits": 0,
        "pnl_samples": [],
        "best_call": None,
        "worst_call": None,
    }


def _finalize_bucket(bucket: dict[str, Any]) -> dict[str, Any]:
    samples: list[float] = bucket.pop("pnl_samples")
    total_buys = bucket["buy_calls"]
    avg_pnl: Optional[float] = sum(samples) / len(samples) if samples else None
    hit_rate: Optional[float] = (
        (bucket["hits"] / total_buys) * 100.0 if total_buys > 0 else None
    )
    return {
        **bucket,
        "hit_rate_pct": hit_rate,
        "avg_buy_pnl_pct": avg_pnl,
    }


def _score_sort_key(entry: dict[str, Any]) -> tuple[float, float, int]:
    """Sort primarily by avg P&L desc, then hit-rate desc, then buy_calls."""
    avg = entry.get("avg_buy_pnl_pct")
    hit = entry.get("hit_rate_pct")
    return (
        avg if avg is not None else float("-inf"),
        hit if hit is not None else float("-inf"),
        entry.get("buy_calls", 0),
    )


def _close_on_or_before_points(
    points: list[dict[str, Any]], target: datetime,
) -> Optional[float]:
    """Return the close at or just before ``target`` from a pre-fetched chart."""
    if not points or target is None:
        return None
    target_date = target.date() if hasattr(target, "date") else None
    if target_date is None:
        return None
    chosen: Optional[float] = None
    for point in points:
        ts = point.get("timestamp") if isinstance(point, dict) else None
        if ts is None:
            continue
        ts_date = ts.date() if hasattr(ts, "date") else None
        if ts_date is None:
            continue
        if ts_date > target_date:
            break
        try:
            value = point.get("close")
            if value is not None:
                chosen = float(value)
        except (TypeError, ValueError):
            continue
    return chosen
