"""Aggregated strategy health: PnL today, trades today, streaks, open positions."""
from __future__ import annotations

from fastapi import APIRouter

from app.dependencies import SessionDep, service_error
from app.models import StrategyHealthResponse
from app.services import alpaca_service, pnl_service, strategy_profiles_service

router = APIRouter(prefix="/api/strategy", tags=["strategy_health"])


@router.get("/health", response_model=StrategyHealthResponse)
async def get_strategy_health(session: SessionDep) -> StrategyHealthResponse:
    try:
        summary = await pnl_service.daily_summary(session)
        streak = await pnl_service.recent_streak(session)
    except Exception as exc:
        raise service_error(exc) from exc

    try:
        positions = await alpaca_service.list_positions()
    except Exception:
        positions = []

    try:
        active_name, _params = await strategy_profiles_service.get_active_strategy_execution_profile()
    except Exception:
        active_name = None

    return StrategyHealthResponse(
        active_strategy_name=active_name,
        realized_pnl_today=summary["realized_pnl_today"],
        trades_today=summary["trades_today"],
        wins_today=summary["wins_today"],
        losses_today=summary["losses_today"],
        last_trade_at=summary["last_trade_at"],
        streak_kind=streak["kind"],
        streak_length=streak["length"],
        open_position_count=len(positions),
    )
