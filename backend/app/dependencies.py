from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.network_utils import friendly_service_error_detail

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def service_error(exc: Exception) -> HTTPException:
    """Wrap an unexpected service-layer exception as a 503 with a user-safe detail."""
    return HTTPException(status_code=503, detail=friendly_service_error_detail(exc))
