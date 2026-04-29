"""OS-level credential vault wrapper around the `keyring` package.

`runtime_settings` is the I/O boundary that callers use; THIS module is
the storage backend swap-in for sensitive keys when SECURE_STORAGE_ENABLED
is true. Behavior:

- `is_enabled()` reads SECURE_STORAGE_ENABLED from runtime_settings (the
  master switch is ITSELF stored in SQLite, never in keyring -- chicken-
  and-egg).
- `get_secret(key) -> str | None` reads via keyring; returns None on miss
  or backend error (caller falls back to SQLite).
- `set_secret(key, value)` writes via keyring; returns bool indicating
  success. Caller falls back to SQLite on failure.
- `delete_secret(key)` removes the entry; idempotent.

A "service name" namespace separates this app's secrets from anything
else stored in the same keyring. We use ``newbird-trading-platform``.

We never raise to the caller for keyring failures. Logged at WARNING so
operators can spot a degraded vault without losing their app.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


SERVICE_NAME = "newbird-trading-platform"
ENABLED_SETTING_KEY = "SECURE_STORAGE_ENABLED"


def _keyring_module() -> Any | None:
    """Import keyring lazily; return None if the package is missing OR the
    backend is the `fail` backend (which means no working backend was
    detected on this system).
    """
    try:
        import keyring  # type: ignore[import-not-found]
        from keyring.backends import fail  # type: ignore[import-not-found]
    except ImportError:
        return None
    backend = keyring.get_keyring()
    if isinstance(backend, fail.Keyring):
        logger.warning(
            "secure_storage: keyring is installed but no usable backend "
            "is available -- falling back to SQLite for all settings."
        )
        return None
    return keyring


def is_enabled(runtime_settings_module: Any) -> bool:
    """Master switch -- ALWAYS reads from SQLite via runtime_settings.

    `runtime_settings_module` is passed in (rather than imported at
    module top) to avoid a circular import: runtime_settings imports
    THIS module to wrap get/set, and we don't want a circular boot.
    """
    return runtime_settings_module.get_bool_setting(
        ENABLED_SETTING_KEY, default=False
    )


def get_secret(key: str) -> str | None:
    """Read a secret value. Returns None on miss or any backend error."""
    keyring = _keyring_module()
    if keyring is None:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception:  # noqa: BLE001
        logger.warning(
            "secure_storage: get_password(%s) failed -- falling back to SQLite",
            key,
            exc_info=True,
        )
        return None


def set_secret(key: str, value: str) -> bool:
    """Write a secret. Returns True on success, False on backend failure."""
    keyring = _keyring_module()
    if keyring is None:
        return False
    try:
        keyring.set_password(SERVICE_NAME, key, value)
        return True
    except Exception:  # noqa: BLE001
        logger.warning(
            "secure_storage: set_password(%s) failed -- caller should fall back",
            key,
            exc_info=True,
        )
        return False


def delete_secret(key: str) -> None:
    """Idempotent delete."""
    keyring = _keyring_module()
    if keyring is None:
        return
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except Exception:  # noqa: BLE001
        # Most backends raise PasswordDeleteError when the entry is
        # already absent. Treat as success.
        pass
