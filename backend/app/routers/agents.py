"""AI Council endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from app.dependencies import SessionDep, service_error
from app.models import (
    AnalysisHistoryResponse,
    AnalysisRequest,
    AnalysisView,
    CouncilRequest,
    CouncilResponse,
    PersonasResponse,
    PersonaView,
)
from app.services import agents_service
from core.agents import LLMRouterUnavailableError

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/personas", response_model=PersonasResponse)
async def list_personas() -> PersonasResponse:
    return PersonasResponse(
        items=[PersonaView(**p) for p in agents_service.list_personas_view()]
    )


@router.post("/analyze", response_model=AnalysisView)
async def analyze(request: AnalysisRequest, session: SessionDep) -> AnalysisView:
    try:
        result = await agents_service.analyze(
            session,
            persona_id=request.persona_id,
            symbol=request.symbol,
            question=request.question,
            model=request.model,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {exc}") from exc
    except LLMRouterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return AnalysisView(**result)


@router.post("/council", response_model=CouncilResponse)
async def council(request: CouncilRequest, session: SessionDep) -> CouncilResponse:
    try:
        result = await agents_service.council(
            session,
            persona_ids=request.persona_ids,
            symbol=request.symbol,
            question=request.question,
            model=request.model,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown persona: {exc}") from exc
    except LLMRouterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CouncilResponse(
        symbol=result["symbol"],
        analyses=[AnalysisView(**a) for a in result["analyses"]],
    )


@router.get("/history", response_model=AnalysisHistoryResponse)
async def list_history(
    session: SessionDep,
    symbol: Optional[str] = None,
    persona_id: Optional[str] = None,
    limit: int = 50,
) -> AnalysisHistoryResponse:
    try:
        rows = await agents_service.list_history(
            session, symbol=symbol, persona_id=persona_id, limit=limit,
        )
    except Exception as exc:
        raise service_error(exc) from exc
    return AnalysisHistoryResponse(items=[AnalysisView(**r) for r in rows])
