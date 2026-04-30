"""Alpha Arena endpoints — leaderboard runs + historical scoreboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import RequestLang, SessionDep, service_error
from app.models.arena import (
    ArenaCurrentVerdict,
    ArenaRunRequest,
    ArenaRunResponse,
    ArenaScoreboardEntry,
    ArenaScoreboardResponse,
)
from app.services import arena_service
from core.agents import LLMRouterUnavailableError

router = APIRouter(prefix="/api/arena", tags=["arena"])


@router.post("/run", response_model=ArenaRunResponse)
async def run_arena(
    request: ArenaRunRequest,
    session: SessionDep,
    lang: RequestLang,
) -> ArenaRunResponse:
    try:
        result = await arena_service.run_arena(
            session,
            symbols=request.symbols,
            persona_ids=request.persona_ids,
            lang=lang,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LLMRouterUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ArenaRunResponse(
        current=[ArenaCurrentVerdict(**c) for c in result["current"]],
        scoreboard=[ArenaScoreboardEntry(**s) for s in result["scoreboard"]],
    )


@router.get("/scoreboard", response_model=ArenaScoreboardResponse)
async def get_scoreboard(
    session: SessionDep,
    lookback_days: int = 90,
) -> ArenaScoreboardResponse:
    try:
        result = await arena_service.get_scoreboard(
            session, lookback_days=lookback_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return ArenaScoreboardResponse(
        scoreboard=[ArenaScoreboardEntry(**s) for s in result["scoreboard"]],
        lookback_days=result["lookback_days"],
    )
