"""Webhook notification delivery."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.services import notifications_service


@pytest.mark.asyncio
async def test_dispatch_skips_when_no_webhook_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "")
    # Should not raise even though we never call out anywhere.
    await notifications_service.dispatch_risk_event(
        policy_name="symbol_blocklist",
        decision="deny",
        reason="GME on blocklist",
        symbol="GME",
        side="buy",
        notional=1000.0,
        qty=None,
    )


@pytest.mark.asyncio
async def test_dispatch_swallows_http_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://does-not-resolve.invalid")

    captured: dict[str, Any] = {}

    class _RaisingClient:
        def __init__(self, *args, **kwargs) -> None: pass
        async def __aenter__(self) -> "_RaisingClient": return self
        async def __aexit__(self, *args) -> None: return None
        async def post(self, url: str, **kwargs: Any):  # noqa: ANN401
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            raise RuntimeError("boom")

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _RaisingClient)
    # Should not raise.
    await notifications_service.dispatch_risk_event(
        policy_name="symbol_blocklist",
        decision="deny",
        reason="GME on blocklist",
        symbol="GME",
        side="buy",
        notional=1000.0,
        qty=None,
    )
    assert captured["url"] == "http://does-not-resolve.invalid"
    assert captured["json"]["event"] == "risk_event"
    assert captured["json"]["policy_name"] == "symbol_blocklist"


@pytest.mark.asyncio
async def test_dispatch_sends_expected_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTIFICATIONS_WEBHOOK_URL", "http://hooks.example/abc")

    captured: dict[str, Any] = {}

    class _RecordingClient:
        def __init__(self, *args, **kwargs) -> None: pass
        async def __aenter__(self) -> "_RecordingClient": return self
        async def __aexit__(self, *args) -> None: return None
        async def post(self, url: str, **kwargs: Any):
            captured["url"] = url
            captured["json"] = kwargs.get("json")
            class _R:
                status_code = 200
                def raise_for_status(self) -> None: return None
            return _R()

    monkeypatch.setattr(notifications_service.httpx, "AsyncClient", _RecordingClient)
    await notifications_service.dispatch_risk_event(
        policy_name="max_daily_loss",
        decision="deny",
        reason="daily loss exceeded",
        symbol="AAPL",
        side="buy",
        notional=2_500.0,
        qty=None,
    )
    assert captured["url"] == "http://hooks.example/abc"
    payload = captured["json"]
    assert payload["event"] == "risk_event"
    assert payload["policy_name"] == "max_daily_loss"
    assert payload["symbol"] == "AAPL"
    assert payload["notional"] == 2_500.0
