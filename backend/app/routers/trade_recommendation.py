"""GET /api/trade-recommendations/{symbol} — synthesize concrete advice."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import TradeRecommendationView, TradeStanceView
from app.services import trade_recommendation_service

router = APIRouter(prefix="/api/trade-recommendations", tags=["trade-recommendations"])


@router.get("/{symbol}", response_model=TradeRecommendationView)
async def get_recommendation(
    symbol: str,
    session: SessionDep,
    broker_account_id: Optional[int] = None,
    range: str = "3mo",
) -> TradeRecommendationView:
    """Synthesize a recommendation from cost basis (if any), recent signals,
    and the user's custom stop/take-profit levels."""
    try:
        payload = await trade_recommendation_service.recommend_for_symbol(
            session,
            symbol=symbol,
            broker_account_id=broker_account_id,
            range_name=range,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return TradeRecommendationView(
        symbol=payload["symbol"],
        current_price=payload["current_price"],
        has_position=payload["has_position"],
        avg_cost_basis=payload["avg_cost_basis"],
        total_shares=payload["total_shares"],
        unrealized_pnl_pct=payload["unrealized_pnl_pct"],
        custom_stop_loss=payload["custom_stop_loss"],
        custom_take_profit=payload["custom_take_profit"],
        recent_signals_count=payload["recent_signals_count"],
        stances=[TradeStanceView(**s) for s in payload["stances"]],
        generated_at=payload["generated_at"],
    )
