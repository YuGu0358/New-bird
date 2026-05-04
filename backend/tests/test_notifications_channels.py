"""Multi-channel notification dispatch.

The shared httpx mock records every (url, payload, channel-shape) so we can
assert that:

- Each channel only fires when its setting is configured.
- Failures in one channel do not short-circuit the others.
- Risk events route to all channels with the right body shape.
- Price alerts use the new dispatch_price_alert helper.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services import notifications_service


@pytest.fixture
def captured_posts(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace httpx.AsyncClient with a recorder. Returns the call log."""
    posts: list[dict[str, Any]] = []

    class _RecordingClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_RecordingClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any):
            posts.append({"url": url, "json": kwargs.get("json")})

            class _R:
                status_code = 200

                def raise_for_status(self) -> None:
                    return None

            return _R()

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _RecordingClient)
    return posts


def _clear_channel_envs(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "NOTIFICATIONS_WEBHOOK_URL",
        "NOTIFICATIONS_SLACK_WEBHOOK_URL",
        "NOTIFICATIONS_DISCORD_WEBHOOK_URL",
        "NOTIFICATIONS_TELEGRAM_BOT_TOKEN",
        "NOTIFICATIONS_TELEGRAM_CHAT_ID",
    ):
        monkeypatch.setenv(key, "")


@pytest.mark.asyncio
async def test_dispatch_with_no_channels_is_noop(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="t", summary="s", severity="info", raw={"event": "x"}
        )
    )
    assert captured_posts == []


@pytest.mark.asyncio
async def test_dispatch_routes_to_every_configured_channel(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://wh.invalid/x")
    monkeypatch.setenv("NOTIFICATIONS_SLACK_WEBHOOK_URL", "http://slack.invalid/x")
    monkeypatch.setenv("NOTIFICATIONS_DISCORD_WEBHOOK_URL", "http://discord.invalid/x")
    monkeypatch.setenv("NOTIFICATIONS_TELEGRAM_BOT_TOKEN", "BOT")
    monkeypatch.setenv("NOTIFICATIONS_TELEGRAM_CHAT_ID", "42")

    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="Risk: blocklist",
            summary="GME blocked",
            severity="critical",
            raw={"event": "risk_event", "policy_name": "blocklist"},
        )
    )

    urls = [p["url"] for p in captured_posts]
    assert "http://wh.invalid/x" in urls
    assert "http://slack.invalid/x" in urls
    assert "http://discord.invalid/x" in urls
    assert any(u.startswith("https://api.telegram.org/botBOT/sendMessage") for u in urls)


@pytest.mark.asyncio
async def test_slack_payload_uses_text_field(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_SLACK_WEBHOOK_URL", "http://slack.invalid/x")
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="Hello", summary="world", severity="info", raw={}
        )
    )
    assert len(captured_posts) == 1
    assert "text" in captured_posts[0]["json"]
    assert "Hello" in captured_posts[0]["json"]["text"]


@pytest.mark.asyncio
async def test_discord_payload_uses_content_field(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_DISCORD_WEBHOOK_URL", "http://discord.invalid/x")
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="Hi", summary="there", severity="warning", raw={}
        )
    )
    assert len(captured_posts) == 1
    assert "content" in captured_posts[0]["json"]


@pytest.mark.asyncio
async def test_telegram_skips_when_only_token_set(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    """Telegram needs both token AND chat_id; one alone must not fire."""
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_TELEGRAM_BOT_TOKEN", "BOT")
    # No chat id
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="t", summary="s", severity="info", raw={}
        )
    )
    assert captured_posts == []


@pytest.mark.asyncio
async def test_webhook_posts_raw_event_payload(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    """The generic webhook channel should receive the structured raw dict
    (not the markdown summary)."""
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://wh.invalid/x")
    raw = {"event": "risk_event", "policy_name": "max_loss", "decision": "deny"}
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="t", summary="s", severity="critical", raw=raw
        )
    )
    assert len(captured_posts) == 1
    assert captured_posts[0]["json"] == raw


@pytest.mark.asyncio
async def test_one_failing_channel_does_not_block_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://wh.invalid/x")
    monkeypatch.setenv("NOTIFICATIONS_SLACK_WEBHOOK_URL", "http://slack.invalid/x")

    delivered: list[str] = []

    class _MixedClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_MixedClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any):
            if "wh.invalid" in url:
                raise RuntimeError("webhook blew up")
            delivered.append(url)

            class _R:
                status_code = 200

                def raise_for_status(self) -> None:
                    return None

            return _R()

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _MixedClient)

    # Should not raise even though webhook channel fails.
    await notifications_service.dispatch(
        notifications_service.NotificationEvent(
            title="t", summary="s", severity="info", raw={}
        )
    )
    assert "http://slack.invalid/x" in delivered


@pytest.mark.asyncio
async def test_dispatch_risk_event_severity_critical_for_deny(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_SLACK_WEBHOOK_URL", "http://slack.invalid/x")
    await notifications_service.dispatch_risk_event(
        policy_name="symbol_blocklist",
        decision="deny",
        reason="GME on blocklist",
        symbol="GME",
        side="buy",
        notional=1000.0,
        qty=None,
    )
    assert len(captured_posts) == 1
    text = captured_posts[0]["json"]["text"]
    assert "🚨" in text  # critical badge
    assert "symbol_blocklist" in text
    assert "GME" in text


@pytest.mark.asyncio
async def test_dispatch_price_alert_includes_target_and_change(
    monkeypatch: pytest.MonkeyPatch,
    captured_posts: list[dict[str, Any]],
) -> None:
    _clear_channel_envs(monkeypatch)
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://wh.invalid/x")
    await notifications_service.dispatch_price_alert(
        symbol="AAPL",
        condition=">= 200",
        target_value=200.0,
        current_price=201.5,
        day_change_percent=2.34,
        note="watchlist breakout",
    )
    assert len(captured_posts) == 1
    body = captured_posts[0]["json"]
    assert body["event"] == "price_alert"
    assert body["symbol"] == "AAPL"
    assert body["target_value"] == 200.0
    assert body["current_price"] == 201.5
    assert body["day_change_percent"] == 2.34
    assert body["note"] == "watchlist breakout"
