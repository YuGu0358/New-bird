from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.services.network_utils import friendly_service_error_detail
from core.broker import Broker, get_broker
from core.i18n import DEFAULT_LANG, normalize_lang

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _resolve_broker() -> Broker:
    """Resolve the active broker per the ``BROKER_BACKEND`` runtime setting."""
    return get_broker()


BrokerDep = Annotated[Broker, Depends(_resolve_broker)]


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


def _require_admin_token(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
) -> None:
    """Gate write endpoints behind SETTINGS_ADMIN_TOKEN when it is configured.

    When the env var is unset (default for solo developers running locally),
    this is a no-op — preserves the existing single-user pattern. When set
    on a shared deploy, every write request must carry the matching value
    in the ``X-Admin-Token`` header or the request is rejected with 401.

    Apply via ``router.get(..., dependencies=[Depends(AdminTokenDep)])``
    or ``Depends(AdminTokenDep)`` in the handler signature.
    """
    from app import runtime_settings

    if not runtime_settings.is_admin_token_required():
        return
    try:
        runtime_settings.validate_admin_token(x_admin_token)
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


AdminTokenDep = Depends(_require_admin_token)
