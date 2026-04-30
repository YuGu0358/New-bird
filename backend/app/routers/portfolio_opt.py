"""Mean-variance portfolio optimisation endpoint (PyPortfolioOpt)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.portfolio_opt import (
    PortfolioOptimizeRequest,
    PortfolioOptimizeResponse,
)
from app.services import portfolio_opt_service

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


@router.post("/optimize", response_model=PortfolioOptimizeResponse)
async def optimize_portfolio(
    request: PortfolioOptimizeRequest,
) -> PortfolioOptimizeResponse:
    """Mean-variance portfolio optimisation across the supplied tickers.

    Modes:
    - `max_sharpe`: maximise Sharpe ratio at the given risk-free rate.
    - `min_volatility`: minimise portfolio volatility.
    - `efficient_return`: minimise volatility subject to `target_return`.
    """
    try:
        payload = await portfolio_opt_service.run_optimization(
            tickers=request.tickers,
            lookback_days=request.lookback_days,
            mode=request.mode,
            target_return=request.target_return,
            risk_free_rate=request.risk_free_rate,
            backend=request.backend,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        # No upstream data — degrade to 503 so the UI can show a "try
        # again later" instead of a generic 500.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return PortfolioOptimizeResponse(**payload)
