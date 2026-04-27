"""Async wrapper around BacktestEngine + persistence."""
from __future__ import annotations

import json
from datetime import date as DateType, datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import BacktestRun, BacktestTrade, init_database
from app.models import StrategyExecutionParameters

import strategies  # noqa: F401  -- ensure decorators have run

from core.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    load_daily_bars,
)
from core.broker.base import Broker
from core.risk import RiskGuard
from core.strategy.registry import default_registry


def _serialize_equity_curve(curve: list[tuple[datetime, float]]) -> str:
    return json.dumps(
        [{"timestamp": ts.isoformat(), "equity": value} for ts, value in curve],
    )


def _serialize_metrics(metrics: dict[str, float]) -> str:
    return json.dumps({k: round(float(v), 6) for k, v in metrics.items()})


async def run_backtest(
    session: AsyncSession,
    *,
    strategy_name: str,
    parameters: dict[str, Any],
    universe: list[str],
    start_date: DateType,
    end_date: DateType,
    initial_cash: float,
    enable_risk_guard: bool = False,
) -> BacktestRun:
    await init_database()

    strategy_cls = default_registry.get(strategy_name)
    schema = strategy_cls.parameters_schema()
    parsed_params = schema.model_validate({**parameters, "universe_symbols": universe or parameters.get("universe_symbols", [])})

    config = BacktestConfig(
        strategy_name=strategy_name,
        parameters=parsed_params.model_dump(),
        universe=parsed_params.universe_symbols,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
    )

    bars = await load_daily_bars(parsed_params.universe_symbols, start=start_date, end=end_date)

    def _factory(broker: Broker):
        # Strategy concrete classes that accept a `broker` kwarg get one;
        # those that don't (legacy ABC-only) fall back to default-broker init.
        try:
            return strategy_cls(parsed_params, broker=broker)  # type: ignore[call-arg]
        except TypeError:
            return strategy_cls(parsed_params)

    risk_guard_factory = None
    if enable_risk_guard:
        from app.services import risk_service

        view = await risk_service.get_config_view(session)
        policies = risk_service.build_policies_from_config(view)

        def _risk_guard_factory(broker: Broker, snapshot_provider):
            return RiskGuard(broker, policies=policies, snapshot_provider=snapshot_provider)

        risk_guard_factory = _risk_guard_factory

    engine = BacktestEngine(
        config=config,
        strategy_factory=_factory,
        risk_guard_factory=risk_guard_factory,
    )

    started_at = datetime.now(timezone.utc)
    try:
        result: BacktestResult = await engine.run(bars)
        status = "completed"
        error_message = ""
    except Exception as exc:  # noqa: BLE001
        finished_at = datetime.now(timezone.utc)
        run = BacktestRun(
            strategy_name=strategy_name,
            parameters_json=json.dumps(parsed_params.model_dump()),
            universe_json=json.dumps(parsed_params.universe_symbols),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            initial_cash=initial_cash,
            final_cash=initial_cash,
            final_equity=initial_cash,
            metrics_json="{}",
            equity_curve_json="[]",
            started_at=started_at,
            finished_at=finished_at,
            status="failed",
            error_message=str(exc),
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return run

    run = BacktestRun(
        strategy_name=strategy_name,
        parameters_json=json.dumps(parsed_params.model_dump()),
        universe_json=json.dumps(parsed_params.universe_symbols),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        initial_cash=initial_cash,
        final_cash=result.final_cash,
        final_equity=result.final_equity,
        metrics_json=_serialize_metrics(result.metrics),
        equity_curve_json=_serialize_equity_curve(result.equity_curve),
        started_at=result.started_at,
        finished_at=result.finished_at,
        status=status,
        error_message=error_message,
    )
    session.add(run)
    await session.flush()

    for trade in result.trades:
        session.add(
            BacktestTrade(
                run_id=run.id,
                symbol=trade.symbol,
                side=trade.side,
                qty=trade.qty,
                price=trade.price,
                notional=trade.notional,
                reason=trade.reason,
                timestamp=trade.timestamp,
            )
        )
    await session.commit()
    await session.refresh(run)
    return run


def serialize_summary(run: BacktestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "strategy_name": run.strategy_name,
        "start_date": run.start_date,
        "end_date": run.end_date,
        "initial_cash": run.initial_cash,
        "final_cash": run.final_cash,
        "final_equity": run.final_equity,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "error_message": run.error_message,
        "metrics": json.loads(run.metrics_json or "{}"),
    }


async def list_runs(session: AsyncSession, *, limit: int = 50) -> list[dict[str, Any]]:
    await init_database()
    result = await session.execute(
        select(BacktestRun).order_by(desc(BacktestRun.id)).limit(max(1, min(limit, 200)))
    )
    return [serialize_summary(row) for row in result.scalars().all()]


async def get_run_with_trades(session: AsyncSession, run_id: int) -> tuple[BacktestRun, list[BacktestTrade]] | None:
    await init_database()
    run = await session.get(BacktestRun, run_id)
    if run is None:
        return None
    result = await session.execute(
        select(BacktestTrade).where(BacktestTrade.run_id == run_id).order_by(BacktestTrade.id)
    )
    return run, list(result.scalars().all())


async def get_equity_curve(session: AsyncSession, run_id: int) -> list[dict[str, Any]] | None:
    await init_database()
    run = await session.get(BacktestRun, run_id)
    if run is None:
        return None
    return json.loads(run.equity_curve_json or "[]")
