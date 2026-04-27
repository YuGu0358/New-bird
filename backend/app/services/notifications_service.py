"""Webhook notification delivery.

Reads NOTIFICATIONS_WEBHOOK_URL from runtime_settings (which falls back to
the env var). Phase 5 supports a single generic webhook target — Slack,
Discord, and most monitoring systems accept a posted JSON body. Failure
to deliver is silently swallowed: notifications must never break trading.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from app import runtime_settings

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    return str(runtime_settings.get_setting("NOTIFICATIONS_WEBHOOK_URL", "") or "").strip()


async def dispatch_risk_event(
    *,
    policy_name: str,
    decision: str,
    reason: str,
    symbol: str,
    side: str,
    notional: Optional[float],
    qty: Optional[float],
) -> None:
    url = _webhook_url()
    if not url:
        return  # No webhook configured — silent skip.

    payload = {
        "event": "risk_event",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "policy_name": policy_name,
        "decision": decision,
        "reason": reason,
        "symbol": symbol,
        "side": side,
        "notional": notional,
        "qty": qty,
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.5)) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Notification webhook delivery failed for %s", policy_name)
