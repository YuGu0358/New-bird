"""Factor Forge HTTP API.

Thin layer over ``factor_vector_store`` (library reads),
``factor_pipeline`` (evolution runs), and the ``factor_daily_active_universe``
table (universe snapshot reads). The frontend's Factor Forge dashboard
binds directly to the response shapes defined here.
"""
from __future__ import annotations

import logging
from datetime import date as date_cls

from fastapi import APIRouter, HTTPException
from sqlalchemy import desc, select

from app.db.engine import AsyncSessionLocal
from app.db.tables import (
    DailyActiveUniverse,
    FactorEvolutionRun,
    FactorGenerationStat,
    FactorPopulationState,
    FactorRecord,
)
from app.models.factors import (
    ActiveUniverseItem,
    ActiveUniverseResponse,
    EvolutionControlResponse,
    EvolutionStatusResponse,
    FactorEvolutionRunsResponse,
    FactorEvolutionRunView,
    FactorLibraryResponse,
    FactorRecordView,
    GenerationHistoryResponse,
    GenerationStatView,
    PopulationSlotView,
    PopulationSnapshotResponse,
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


@router.get("/evolution/status", response_model=EvolutionStatusResponse)
async def get_evolution_status() -> EvolutionStatusResponse:
    """Live status of the continuous Factor Forge evolution loop."""
    payload = await factor_pipeline.evolution_status()
    return EvolutionStatusResponse(**payload)


@router.post("/evolution/start", response_model=EvolutionControlResponse)
async def start_evolution() -> EvolutionControlResponse:
    """Start the continuous evolution loop (idempotent)."""
    msg = await factor_pipeline.start_loop()
    return EvolutionControlResponse(is_running=True, message=msg)


@router.post("/evolution/stop", response_model=EvolutionControlResponse)
async def stop_evolution() -> EvolutionControlResponse:
    """Stop the continuous evolution loop (idempotent)."""
    msg = await factor_pipeline.stop_loop()
    return EvolutionControlResponse(is_running=False, message=msg)


_HISTORY_MAX_LIMIT = 1000
_HISTORY_DEFAULT_LIMIT = 100


@router.get("/evolution/history", response_model=GenerationHistoryResponse)
async def get_evolution_history(
    limit: int = _HISTORY_DEFAULT_LIMIT,
) -> GenerationHistoryResponse:
    """Per-generation summaries, oldest-first.

    The query selects the most recent ``limit`` rows by generation
    descending, then reverses so the response is in chronological order
    — matches what a line chart consumes directly.
    """
    capped = min(max(int(limit), 1), _HISTORY_MAX_LIMIT)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorGenerationStat)
                .order_by(desc(FactorGenerationStat.generation))
                .limit(capped)
            )
        ).scalars().all()
    ordered = list(reversed(rows))
    items = [GenerationStatView.model_validate(r) for r in ordered]
    return GenerationHistoryResponse(items=items)


@router.get("/evolution/population", response_model=PopulationSnapshotResponse)
async def get_evolution_population() -> PopulationSnapshotResponse:
    """Current GP population: one entry per slot with its formula + fitness."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(FactorPopulationState).order_by(FactorPopulationState.slot)
            )
        ).scalars().all()
    if not rows:
        return PopulationSnapshotResponse(generation=0, slots=[])
    gen = max(int(r.generation) for r in rows)
    slots = [
        PopulationSlotView(
            slot=int(r.slot),
            formula=str(r.formula),
            fitness=float(r.fitness),
        )
        for r in rows
    ]
    return PopulationSnapshotResponse(generation=gen, slots=slots)
