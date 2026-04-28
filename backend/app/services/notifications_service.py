"""Outbound notifications — multi-channel fan-out.

Up to four channels can be enabled in parallel; each is gated by its own
runtime_settings key so users opt in by filling in the URL/token. Failures
in one channel never leak to another (and never break trading).

| Channel | Settings key(s)                                            | Format                                |
|---------|------------------------------------------------------------|---------------------------------------|
| webhook | NOTIFICATIONS_WEBHOOK_URL                                  | raw structured event JSON             |
| slack   | NOTIFICATIONS_SLACK_WEBHOOK_URL                            | {"text": "..."} markdown              |
| discord | NOTIFICATIONS_DISCORD_WEBHOOK_URL                          | {"content": "..."} markdown           |
| telegram| NOTIFICATIONS_TELEGRAM_BOT_TOKEN + NOTIFICATIONS_TELEGRAM_CHAT_ID | sendMessage with text + Markdown |

All channels share a 5s timeout and swallow exceptions individually.
The original single-webhook behaviour is preserved: setting only
NOTIFICATIONS_WEBHOOK_URL still POSTs the same structured payload.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx

from app import runtime_settings

logger = logging.getLogger(__name__)


_TIMEOUT = httpx.Timeout(5.0, connect=2.5)


@dataclass
class NotificationEvent:
    """Channel-agnostic event passed through every dispatcher.

    `raw` is the JSON the generic webhook channel posts verbatim. The chat
    channels (slack/discord/telegram) format a markdown summary instead.
    """

    title: str
    summary: str
    severity: str  # "info" | "warning" | "critical"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------- channel implementations ----------


def _setting(key: str) -> str:
    return str(runtime_settings.get_setting(key, "") or "").strip()


async def _post_json(url: str, payload: dict[str, Any], *, channel: str) -> None:
    """Single POST; raise_for_status; caller-owned try/except."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
    except Exception:
        logger.exception("Notification channel %s delivery failed", channel)


async def _send_webhook(event: NotificationEvent) -> None:
    url = _setting("NOTIFICATIONS_WEBHOOK_URL")
    if not url:
        return
    await _post_json(url, event.raw, channel="webhook")


def _markdown_summary(event: NotificationEvent) -> str:
    """Compose a short markdown block: bold title, severity badge, summary."""
    badge = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(event.severity, "")
    head = f"{badge} *{event.title}*".strip()
    return f"{head}\n{event.summary}"


async def _send_slack(event: NotificationEvent) -> None:
    url = _setting("NOTIFICATIONS_SLACK_WEBHOOK_URL")
    if not url:
        return
    await _post_json(url, {"text": _markdown_summary(event)}, channel="slack")


async def _send_discord(event: NotificationEvent) -> None:
    url = _setting("NOTIFICATIONS_DISCORD_WEBHOOK_URL")
    if not url:
        return
    # Discord truncates >2000 chars; our summaries are short but be safe.
    content = _markdown_summary(event)[:1900]
    await _post_json(url, {"content": content}, channel="discord")


async def _send_telegram(event: NotificationEvent) -> None:
    token = _setting("NOTIFICATIONS_TELEGRAM_BOT_TOKEN")
    chat_id = _setting("NOTIFICATIONS_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": _markdown_summary(event),
        "parse_mode": "Markdown",
    }
    await _post_json(url, payload, channel="telegram")


# Order chosen so the most reliable channel runs first. Failures in any one
# channel never short-circuit the others.
_CHANNELS: tuple[Callable[[NotificationEvent], Awaitable[None]], ...] = (
    _send_webhook,
    _send_slack,
    _send_discord,
    _send_telegram,
)


async def dispatch(event: NotificationEvent) -> None:
    """Fan-out the event to every configured channel."""
    for sender in _CHANNELS:
        try:
            await sender(event)
        except Exception:
            # Defense in depth — _post_json already swallows, but a sender
            # could raise before reaching the POST.
            logger.exception("Notification sender %s raised", sender.__name__)


# ---------- domain-specific helpers ----------


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
    """Risk-policy decision (deny / warn) — formatted across all channels."""
    raw = {
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
    summary_lines = [
        f"Policy: `{policy_name}` → *{decision}*",
        f"Symbol: {symbol} ({side})",
        f"Reason: {reason}",
    ]
    if notional is not None:
        summary_lines.append(f"Notional: ${notional:,.2f}")
    if qty is not None:
        summary_lines.append(f"Qty: {qty}")
    severity = "critical" if decision.lower() == "deny" else "warning"
    await dispatch(
        NotificationEvent(
            title=f"Risk: {policy_name}",
            summary="\n".join(summary_lines),
            severity=severity,
            raw=raw,
        )
    )


async def dispatch_price_alert(
    *,
    symbol: str,
    condition: str,
    target_value: float | None,
    current_price: float,
    day_change_percent: float | None,
    note: str | None = None,
) -> None:
    """Price-alert trigger — multi-channel notification."""
    raw = {
        "event": "price_alert",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "condition": condition,
        "target_value": target_value,
        "current_price": current_price,
        "day_change_percent": day_change_percent,
        "note": note,
    }
    summary_lines = [
        f"Symbol: *{symbol}*",
        f"Condition: {condition}",
        f"Current: ${current_price:,.2f}",
    ]
    if target_value is not None:
        summary_lines.append(f"Target: {target_value}")
    if day_change_percent is not None:
        summary_lines.append(f"Day Δ: {day_change_percent:+.2f}%")
    if note:
        summary_lines.append(f"Note: {note}")
    await dispatch(
        NotificationEvent(
            title=f"Alert: {symbol}",
            summary="\n".join(summary_lines),
            severity="info",
            raw=raw,
        )
    )
