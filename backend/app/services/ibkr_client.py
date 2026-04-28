"""Thin async wrapper around ``ib_async.IB`` for IBKR Gateway connections.

The rest of the service uses ``async with get_client() as ib:`` and lets this
module own the lifecycle (connect on enter, disconnect on exit). A single
``IB()`` is used per request — pooling can be added later if needed.

Reads ``IBKR_HOST`` / ``IBKR_PORT`` / ``IBKR_CLIENT_ID`` from
``runtime_settings``. The settings are not yet registered in
``SETTING_DEFINITIONS``; that lands in a later task. Until then unset values
come back as empty strings and trigger ``IBKRConfigError`` here.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ib_async import IB

from app import runtime_settings

# Timeout for the lightweight reachability probe used by /api/health/ready.
_REACHABILITY_TIMEOUT_SECONDS = 2.0


class IBKRConfigError(RuntimeError):
    """Raised when IBKR_HOST / IBKR_PORT / IBKR_CLIENT_ID are missing."""


def _load_connection_settings() -> tuple[str, int, int]:
    """Return (host, port, client_id), raising ``IBKRConfigError`` if missing."""

    host = (runtime_settings.get_setting("IBKR_HOST", "") or "").strip()
    port_raw = (runtime_settings.get_setting("IBKR_PORT", "") or "").strip()
    client_id_raw = (runtime_settings.get_setting("IBKR_CLIENT_ID", "") or "").strip()

    missing = [
        name
        for name, value in (
            ("IBKR_HOST", host),
            ("IBKR_PORT", port_raw),
            ("IBKR_CLIENT_ID", client_id_raw),
        )
        if not value
    ]
    if missing:
        raise IBKRConfigError(
            "IBKR connection settings are not configured: " + ", ".join(missing)
        )

    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise IBKRConfigError(f"IBKR_PORT must be an integer, got {port_raw!r}") from exc

    try:
        client_id = int(client_id_raw)
    except (TypeError, ValueError) as exc:
        raise IBKRConfigError(
            f"IBKR_CLIENT_ID must be an integer, got {client_id_raw!r}"
        ) from exc

    return host, port, client_id


@asynccontextmanager
async def get_client() -> AsyncIterator[IB]:
    """Yield a connected ``ib_async.IB`` instance and disconnect on exit.

    Reads ``IBKR_HOST``, ``IBKR_PORT`` (int) and ``IBKR_CLIENT_ID`` (int) from
    ``runtime_settings``. Raises :class:`IBKRConfigError` if any are missing,
    and ``ConnectionRefusedError`` (from ``ib_async``) if the Gateway is not
    reachable. ``IB.disconnect()`` always runs in the finally block.
    """

    host, port, client_id = _load_connection_settings()
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id)
        yield ib
    finally:
        # disconnect() is sync in ib_async and safe to call even if connect
        # never succeeded.
        ib.disconnect()


async def is_reachable() -> bool:
    """Lightweight TCP probe used by ``/api/health/ready``.

    Returns ``True`` if a connection succeeds within
    ``_REACHABILITY_TIMEOUT_SECONDS``, ``False`` otherwise. Never raises —
    every error path (missing config, refused connection, timeout, anything
    else) is folded into ``False``.
    """

    try:
        host, port, client_id = _load_connection_settings()
    except IBKRConfigError:
        return False
    except Exception:
        # Defensive: never let setting-read failures leak out of the probe.
        return False

    ib = IB()
    try:
        try:
            await asyncio.wait_for(
                ib.connectAsync(host, port, clientId=client_id),
                timeout=_REACHABILITY_TIMEOUT_SECONDS,
            )
        except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
            return False
        except Exception:
            return False
        return True
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass
