from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    SocialProviderStatus,
    SocialSearchResponse,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
)
from app.services import social_intelligence_service, social_signal_service

router = APIRouter(prefix="/api/social", tags=["social"])


@router.get("/providers", response_model=list[SocialProviderStatus])
async def get_social_providers() -> list[SocialProviderStatus]:
    payload = social_intelligence_service.list_social_providers()
    return [SocialProviderStatus(**item) for item in payload]


@router.get("/search", response_model=SocialSearchResponse)
async def search_social(
    session: SessionDep,
    query: str,
    provider: str = "x",
    limit: int = 20,
    lang: str | None = None,
    min_like_count: int = 0,
    min_repost_count: int = 0,
    exclude_reposts: bool = True,
    exclude_replies: bool = True,
    exclude_terms: list[str] | None = None,
    summarize: bool = False,
    force_refresh: bool = False,
) -> SocialSearchResponse:
    try:
        payload = await social_intelligence_service.search_social_posts(
            session,
            provider=provider,
            query=query,
            limit=limit,
            lang=lang,
            min_like_count=min_like_count,
            min_repost_count=min_repost_count,
            exclude_reposts=exclude_reposts,
            exclude_replies=exclude_replies,
            exclude_terms=exclude_terms or (),
            summarize=summarize,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSearchResponse(**payload)


@router.get("/score", response_model=SocialSignalSnapshotView)
async def score_social_signal(
    session: SessionDep,
    symbol: str,
    keyword: list[str] | None = None,
    hours: int = 6,
    lang: str = "en",
    execute: bool = False,
    force_refresh: bool = False,
) -> SocialSignalSnapshotView:
    try:
        payload = await social_signal_service.score_symbol_signal(
            session,
            symbol=symbol,
            keywords=keyword or (),
            hours=hours,
            lang=lang,
            execute=execute,
            force_refresh=force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSignalSnapshotView(**payload)


@router.get("/signals", response_model=list[SocialSignalSnapshotView])
async def get_social_signals(
    session: SessionDep,
    symbol: str | None = None,
    limit: int = 25,
) -> list[SocialSignalSnapshotView]:
    try:
        payload = await social_signal_service.get_latest_signals(
            session,
            symbol=symbol,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return [SocialSignalSnapshotView(**item) for item in payload]


@router.post("/run", response_model=SocialSignalRunResponse)
async def run_social_signals(
    request: SocialSignalRunRequest,
    session: SessionDep,
) -> SocialSignalRunResponse:
    try:
        payload = await social_signal_service.run_social_monitor(
            session,
            symbols=request.symbols,
            keywords=request.keywords,
            include_watchlist=request.include_watchlist,
            include_positions=request.include_positions,
            include_candidates=request.include_candidates,
            hours=request.hours,
            lang=request.lang,
            execute=request.execute,
            force_refresh=request.force_refresh,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return SocialSignalRunResponse(**payload)
