from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.network_utils import friendly_service_error_detail
from core.i18n import DEFAULT_LANG, normalize_lang

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _resolve_request_lang(
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
    lang_query: str | None = None,
) -> str:
    """Pick the response language for an HTTP request.

    Order of precedence:
    1. Explicit `?lang=` query param (handy for shareable URLs and tests).
    2. The browser-supplied `Accept-Language` header — the frontend pushes
       the active i18next locale here on every fetch.
    3. `DEFAULT_LANG` (English) when neither is present.

    The result is always one of `core.i18n.SUPPORTED_LANGS`.
    """
    return normalize_lang(lang_query or accept_language or DEFAULT_LANG)


RequestLang = Annotated[str, Depends(_resolve_request_lang)]


def service_error(exc: Exception) -> HTTPException:
    """Wrap an unexpected service-layer exception as a 503 with a user-safe detail."""
    return HTTPException(status_code=503, detail=friendly_service_error_detail(exc))
