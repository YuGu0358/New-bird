from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class RuntimeSettingItem(BaseModel):
    key: str
    label: str
    category: str
    required: bool
    sensitive: bool
    configured: bool
    source: str
    value: Optional[str] = None
    description: str = ""


class RuntimeSettingsStatus(BaseModel):
    is_ready: bool
    admin_token_required: bool
    missing_required_keys: list[str]
    items: list[RuntimeSettingItem]
    updated_keys: list[str] = []


class SettingsUpdateRequest(BaseModel):
    admin_token: Optional[str] = None
    settings: dict[str, Any]
