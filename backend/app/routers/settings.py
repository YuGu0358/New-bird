from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import runtime_settings
from app.dependencies import service_error
from app.models import RuntimeSettingsStatus, SettingsUpdateRequest

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/status", response_model=RuntimeSettingsStatus)
async def get_runtime_settings_status() -> RuntimeSettingsStatus:
    return RuntimeSettingsStatus(**runtime_settings.get_settings_status())


@router.put("", response_model=RuntimeSettingsStatus)
async def update_runtime_settings(request: SettingsUpdateRequest) -> RuntimeSettingsStatus:
    try:
        payload = runtime_settings.save_settings(
            request.settings,
            admin_token=request.admin_token,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return RuntimeSettingsStatus(**payload)
