"""Factor Forge HTTP API.

Thin layer over ``factor_vector_store`` (library reads),
``factor_pipeline`` (evolution runs), and the ``factor_daily_active_universe``
table (universe snapshot reads). The frontend's Factor Forge dashboard
binds directly to the response shapes defined here.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls

from fastapi import APIRouter, BackgroundTasks, HTTPException
from sqlalchemy import desc, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import DailyActiveUniverse, FactorEvolutionRun, FactorRecord
from app.models.factors import (
    ActiveUniverseItem,
    ActiveUniverseResponse,
    FactorEvolutionRunsResponse,
    FactorEvolutionRunView,
    FactorLibraryResponse,
    FactorRecordView,
    RunEvolutionResponse,
)
from app.services import factor_pipeline, factor_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("/library", response_model=FactorLibraryResponse)
async def list_library(
    limit: int = 100,
    sort_by: str = "fitness",
    min_fitness: float | None = None,
) -> FactorLibraryResponse:
    """Return the top factors from the vector store, sorted by ``sort_by``."""
    items = await factor_vector_store.list_factors(
        limit=limit, sort_by=sort_by, min_fitness=min_fitness
    )
    return FactorLibraryResponse(
        items=[FactorRecordView.model_validate(item) for item in items]
    )


@router.get("/library/{factor_id}", response_model=FactorRecordView)
async def get_factor(factor_id: int) -> FactorRecordView:
    """Fetch a single factor record by id."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorRecord).where(FactorRecord.id == factor_id)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="factor not found")
    return FactorRecordView.model_validate(row)


@router.get("/active-universe", response_model=ActiveUniverseResponse)
async def get_active_universe(
    query_date: date_cls | None = None,
    top_n: int = 100,
) -> ActiveUniverseResponse:
    """Return today's (or ``query_date``'s) ranked active universe."""
    target = query_date or date_cls.today()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(DailyActiveUniverse)
                .where(DailyActiveUniverse.date == target)
                .order_by(DailyActiveUniverse.rank)
                .limit(top_n)
            )
        ).scalars().all()
    items = [
        ActiveUniverseItem(
            rank=r.rank,
            symbol=r.symbol,
            activity_score=r.activity_score,
            dollar_volume=r.dollar_volume,
        )
        for r in rows
    ]
    return ActiveUniverseResponse(date=target, items=items)


@router.get("/runs", response_model=FactorEvolutionRunsResponse)
async def list_runs(limit: int = 20) -> FactorEvolutionRunsResponse:
    """Most-recent evolution runs first."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorEvolutionRun)
                .order_by(desc(FactorEvolutionRun.started_at))
                .limit(limit)
            )
        ).scalars().all()
    items = [FactorEvolutionRunView.model_validate(r) for r in rows]
    return FactorEvolutionRunsResponse(items=items)


@router.get("/runs/{run_id}", response_model=FactorEvolutionRunView)
async def get_run(run_id: int) -> FactorEvolutionRunView:
    """Fetch a single run's status / stats."""
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionRun).where(FactorEvolutionRun.id == run_id)
            )
        ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return FactorEvolutionRunView.model_validate(row)


@router.post("/run-evolution", response_model=RunEvolutionResponse)
async def run_evolution(background_tasks: BackgroundTasks) -> RunEvolutionResponse:
    """Queue a manual evolution run; returns immediately with the run id."""
    run_id = await factor_pipeline._create_run()
    background_tasks.add_task(_runner_then_finish, run_id)
    return RunEvolutionResponse(run_id=run_id, status="queued")


async def _runner_then_finish(placeholder_run_id: int) -> None:
    """Background body: clear the placeholder row, then run the full pipeline.

    The placeholder is created synchronously in ``run_evolution`` so the
    HTTP caller gets a real, persisted id back. ``run_full_pipeline``
    creates its own row, so we delete the placeholder first to avoid a
    duplicate ``running`` entry hanging around.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(FactorEvolutionRun).where(
                    FactorEvolutionRun.id == placeholder_run_id
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            await session.delete(row)
            await session.commit()
    await factor_pipeline.run_full_pipeline()
