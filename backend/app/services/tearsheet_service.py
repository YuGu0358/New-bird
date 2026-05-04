"""Backtest tearsheet — pulls equity curve from backtest_service, runs metrics."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import backtest_service
from core.quantstats import compute_tearsheet


def _extract_equity_values(curve: list[dict[str, Any]]) -> list[float]:
    """Pull just the numeric values from the equity-curve dicts.

    backtest_service stores points as {"timestamp": ..., "equity": float};
    we also accept "value" as a fallback for forward-compat. Be tolerant:
    skip any point whose value is missing / not numeric so a single corrupt
    row doesn't poison the whole tearsheet.
    """
    out: list[float] = []
    for point in curve:
        if not isinstance(point, dict):
            continue
        raw = point.get("equity")
        if raw is None:
            raw = point.get("value")
        if raw is None:
            continue
        try:
            out.append(float(raw))
        except (TypeError, ValueError):
            continue
    return out


async def get_tearsheet(
    session: AsyncSession,
    run_id: int,
    *,
    periods_per_year: int = 252,
    risk_free_rate: float = 0.04,
) -> dict[str, Any] | None:
    """Compute the tearsheet for a stored backtest run.

    Returns:
        Dict shaped for `TearsheetResponse`, or None when the run_id
        doesn't exist (router translates to HTTP 404).
    """
    curve = await backtest_service.get_equity_curve(session, run_id)
    if curve is None:
        return None

    equity_values = _extract_equity_values(curve)
    metrics = compute_tearsheet(
        equity_values,
        periods_per_year=periods_per_year,
        risk_free_rate=risk_free_rate,
    )

    return {
        "run_id": run_id,
        "periods_per_year": periods_per_year,
        "risk_free_rate": risk_free_rate,
        "cagr": metrics.cagr,
        "volatility": metrics.volatility,
        "sharpe": metrics.sharpe,
        "sortino": metrics.sortino,
        "max_drawdown": metrics.max_drawdown,
        "calmar": metrics.calmar,
        "total_return": metrics.total_return,
        "periods": metrics.periods,
        "generated_at": datetime.now(timezone.utc),
    }
