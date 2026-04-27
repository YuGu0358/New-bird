"""User strategy code endpoints — upload / list / source / reload / delete."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    UserStrategyDetail,
    UserStrategyListResponse,
    UserStrategyUploadRequest,
    UserStrategyView,
)
from app.services import code_service
from app.services.code_service import CodeServiceError

router = APIRouter(prefix="/api/code", tags=["code"])


@router.get("/strategies", response_model=UserStrategyListResponse)
async def list_strategies(session: SessionDep) -> UserStrategyListResponse:
    try:
        rows = await code_service.list_user_strategies(session)
    except Exception as exc:
        raise service_error(exc) from exc
    return UserStrategyListResponse(items=[UserStrategyView(**r) for r in rows])


@router.post("/upload", response_model=UserStrategyView)
async def upload_strategy(
    request: UserStrategyUploadRequest,
    session: SessionDep,
) -> UserStrategyView:
    try:
        result = await code_service.save_user_strategy(
            session,
            slot_name=request.slot_name,
            display_name=request.display_name,
            description=request.description,
            source_code=request.source_code,
        )
    except CodeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return UserStrategyView(**result)


@router.get("/strategies/{strategy_id}/source", response_model=UserStrategyDetail)
async def get_source(strategy_id: int, session: SessionDep) -> UserStrategyDetail:
    try:
        row = await code_service.get_user_strategy(session, strategy_id)
    except Exception as exc:
        raise service_error(exc) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"User strategy {strategy_id} not found")
    return UserStrategyDetail(**row)


@router.post("/strategies/{strategy_id}/reload", response_model=UserStrategyView)
async def reload_strategy(strategy_id: int, session: SessionDep) -> UserStrategyView:
    try:
        result = await code_service.reload_user_strategy(session, strategy_id)
    except CodeServiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return UserStrategyView(**result)


@router.delete("/strategies/{strategy_id}", response_model=dict)
async def delete_strategy(strategy_id: int, session: SessionDep) -> dict:
    try:
        deleted = await code_service.delete_user_strategy(session, strategy_id)
    except Exception as exc:
        raise service_error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"User strategy {strategy_id} not found")
    return {"deleted": True, "id": strategy_id}
