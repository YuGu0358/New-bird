"""Liveness + readiness probes."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import select

from app import runtime_settings
from app.dependencies import SessionDep
from app.database import StrategyProfile
from app.models import HealthResponse, ReadinessCheck, ReadinessResponse
from app.services import ibkr_client

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Always 200 if the process can answer HTTP. Useful for k8s liveness."""
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(session: SessionDep) -> ReadinessResponse:
    """Probe DB + framework registry. Returns 200 with ready=false on partial degradation."""
    checks: list[ReadinessCheck] = []

    # DB ping.
    try:
        await session.execute(select(StrategyProfile).limit(1))
        checks.append(ReadinessCheck(name="database", ok=True))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="database", ok=False, detail=str(exc)))

    # Strategy registry resolves the default strategy.
    try:
        import strategies  # noqa: F401  -- decorators
        from core.strategy.registry import default_registry

        default_registry.get("strategy_b_v1")
        checks.append(ReadinessCheck(name="strategy_registry", ok=True))
    except Exception as exc:  # noqa: BLE001
        checks.append(ReadinessCheck(name="strategy_registry", ok=False, detail=str(exc)))

    # IBKR reachability — only fail readiness when IBKR is the active backend.
    backend = (runtime_settings.get_setting("BROKER_BACKEND", "alpaca") or "").strip().lower()
    if backend != "ibkr":
        checks.append(ReadinessCheck(name="ibkr.reachable", ok=True, detail="not in use"))
    else:
        try:
            reachable = await ibkr_client.is_reachable()
        except Exception as exc:  # noqa: BLE001 -- defensive; is_reachable is documented not to raise
            checks.append(
                ReadinessCheck(name="ibkr.reachable", ok=False, detail=str(exc))
            )
        else:
            if reachable:
                checks.append(
                    ReadinessCheck(name="ibkr.reachable", ok=True, detail="reachable")
                )
            else:
                checks.append(
                    ReadinessCheck(
                        name="ibkr.reachable",
                        ok=False,
                        detail="IB Gateway unreachable on configured host:port",
                    )
                )

    return ReadinessResponse(ready=all(c.ok for c in checks), checks=checks)
