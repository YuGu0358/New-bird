"""Backtest API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    BacktestEquityCurveResponse,
    BacktestEquityPoint,
    BacktestRunRequest,
    BacktestRunResponse,
    BacktestRunsListResponse,
    BacktestSummaryView,
    BacktestTradeView,
)
from app.services import backtest_service

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


@router.post("/run", response_model=BacktestSummaryView)
async def run_backtest(
    request: BacktestRunRequest,
    session: SessionDep,
) -> BacktestSummaryView:
    try:
        run = await backtest_service.run_backtest(
            session,
            strategy_name=request.strategy_name,
            parameters=request.parameters,
            universe=request.universe,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_cash=request.initial_cash,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown strategy: {exc}") from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return BacktestSummaryView(**backtest_service.serialize_summary(run))


@router.get("/runs", response_model=BacktestRunsListResponse)
async def list_runs(session: SessionDep) -> BacktestRunsListResponse:
    items = await backtest_service.list_runs(session)
    return BacktestRunsListResponse(items=[BacktestSummaryView(**i) for i in items])


@router.get("/{run_id}", response_model=BacktestRunResponse)
async def get_run(run_id: int, session: SessionDep) -> BacktestRunResponse:
    payload = await backtest_service.get_run_with_trades(session, run_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")
    run, trades = payload
    summary = BacktestSummaryView(**backtest_service.serialize_summary(run))
    trade_views = [
        BacktestTradeView(
            symbol=t.symbol,
            side=t.side,
            qty=t.qty,
            price=t.price,
            notional=t.notional,
            reason=t.reason,
            timestamp=t.timestamp,
        )
        for t in trades
    ]
    return BacktestRunResponse(summary=summary, trades=trade_views)


@router.get("/{run_id}/equity-curve", response_model=BacktestEquityCurveResponse)
async def get_equity_curve(run_id: int, session: SessionDep) -> BacktestEquityCurveResponse:
    points = await backtest_service.get_equity_curve(session, run_id)
    if points is None:
        raise HTTPException(status_code=404, detail=f"Backtest run {run_id} not found")
    return BacktestEquityCurveResponse(
        run_id=run_id,
        points=[
            BacktestEquityPoint(timestamp=p["timestamp"], equity=p["equity"])
            for p in points
        ],
    )
