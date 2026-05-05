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
    LandscapePoint,
    LandscapeResponse,
    PopulationSlotView,
    PopulationSnapshotResponse,
    QARequest,
    QAResponse,
    QAToolCall,
    RecommendationView,
    RecommendationsResponse,
    TrajectoriesResponse,
    TrajectoryNodeView,
)
from app.services import (
    factor_landscape_service,
    factor_pipeline,
    factor_qa_service,
    factor_quanta_service,
    factor_vector_store,
    today_recommendations_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/factors", tags=["factors"])


@router.get("/library", response_model=FactorLibraryResponse)
async def list_library(
    limit: int = 100,
    sort_by: str = "fitness",
    min_fitness: float | None = None,
    include_quarantined: bool = False,
) -> FactorLibraryResponse:
    """Return the top factors from the vector store, sorted by ``sort_by``.

    By default quarantined (suspicious) factors are excluded — pass
    ``include_quarantined=true`` to see them too.
    """
    items = await factor_vector_store.list_factors(
        limit=limit,
        sort_by=sort_by,
        min_fitness=min_fitness,
        include_quarantined=include_quarantined,
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


@router.post("/admin/refresh-data")
async def admin_refresh_data() -> dict[str, str]:
    """One-shot trigger for the daily data-refresh job.

    Useful right after a fresh deploy where the persistent volume is
    empty — fills factor_daily_bars + active universe + symbol meta +
    news features so the evolution loop has something to evaluate.
    Synchronous: returns once the refresh completes (a few minutes).
    """
    await factor_pipeline.daily_data_refresh()
    return {"status": "ok", "message": "daily data refresh complete"}


@router.post("/admin/purge-bad-records")
async def admin_purge_bad_records() -> dict[str, int]:
    """Delete factor_records rows that slipped past the gate with bad
    metrics: ``fitness <= 0`` or any NaN core metric.

    Returns ``{"deleted": N}``. Idempotent.
    """
    from sqlalchemy import delete, or_

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(FactorRecord).where(
                or_(
                    FactorRecord.fitness <= 0.0,
                    FactorRecord.fitness.is_(None),
                    FactorRecord.ic_5d.is_(None),
                )
            )
        )
        await session.commit()
        deleted = int(result.rowcount or 0)
    return {"deleted": deleted}


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


@router.get("/landscape", response_model=LandscapeResponse)
async def get_landscape(limit: int = 500) -> LandscapeResponse:
    """PCA-2D projection of factor formula embeddings, sorted by fitness."""
    capped = min(max(int(limit), 1), 2000)
    points = await factor_landscape_service.compute_landscape(limit=capped)
    return LandscapeResponse(items=[LandscapePoint(**p) for p in points])


@router.get("/recommendations/today", response_model=RecommendationsResponse)
async def get_today_recommendations(top_k: int = 10) -> RecommendationsResponse:
    """Return today's persisted recommendations.

    Generates them on the first hit of the day if the table is empty so
    the UI never sees a stale-but-loadable empty state when the cron
    hasn't fired yet (e.g. dev server boot).
    """
    items = await today_recommendations_service.get_today_recommendations()
    if not items:
        half = max(1, top_k // 2)
        await today_recommendations_service.generate_today_recommendations(
            top_k_buy=half, top_k_sell=top_k - half
        )
        items = await today_recommendations_service.get_today_recommendations()
    return RecommendationsResponse(
        items=[RecommendationView.model_validate(it) for it in items[:top_k]],
        generated_at=items[0]["date"] if items else None,
    )


@router.get("/trajectories", response_model=TrajectoriesResponse)
async def list_trajectories(limit: int = 200) -> TrajectoriesResponse:
    """Recent QuantaAlpha trajectories — drives the evolution lineage tree."""
    capped = min(max(int(limit), 1), 1000)
    items = await factor_quanta_service.list_trajectories(limit=capped)
    return TrajectoriesResponse(
        items=[TrajectoryNodeView.model_validate(it) for it in items]
    )


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


@router.post("/qa", response_model=QAResponse)
async def factor_qa(body: QARequest) -> QAResponse:
    """Natural-language Q&A using OpenAI tool-calling over our pre-defined tools.

    SECURITY: the LLM never writes/executes Python — it only picks from a
    whitelisted tool registry. Question is also keyword-screened.
    """
    if not body.question or not body.question.strip():
        raise HTTPException(status_code=400, detail="question is empty")
    result = await factor_qa_service.answer_question(body.question.strip())
    return QAResponse(
        answer=result["answer"],
        tool_calls=[QAToolCall(**tc) for tc in result.get("tool_calls", [])],
        blocked=bool(result.get("blocked", False)),
    )
