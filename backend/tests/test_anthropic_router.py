"""Unit tests for AnthropicLLMRouter and the provider dispatcher.

Covers the four contract points the router promises callers:
1. Raises LLMRouterUnavailableError when no API key is configured.
2. Parses text out of a stubbed Anthropic Messages response.
3. get_default_router() defaults to OpenAI for backwards compatibility.
4. get_default_router() picks AnthropicLLMRouter when COUNCIL_LLM_PROVIDER='anthropic'.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.agents.llm_router import (
    AnthropicLLMRouter,
    LLMRouterUnavailableError,
    OpenAILLMRouter,
    get_default_router,
)


@pytest.mark.asyncio
async def test_anthropic_router_unavailable_when_unconfigured(monkeypatch) -> None:
    # Arrange — pretend the Anthropic key has not been set.
    from app.services import anthropic_service

    monkeypatch.setattr(anthropic_service, "is_configured", lambda: False)
    router = AnthropicLLMRouter()

    # Act + Assert — calling generate without a key must raise the
    # unavailable variant so callers can distinguish "not set up" from
    # "request failed".
    with pytest.raises(LLMRouterUnavailableError):
        await router.generate(system="sys", user="usr")


@pytest.mark.asyncio
async def test_anthropic_router_parses_text_block(monkeypatch) -> None:
    # Arrange — stub the Anthropic SDK so we don't hit the network.
    from app.services import anthropic_service

    fake_response = SimpleNamespace(
        content=[SimpleNamespace(text="stub-response")],
        model="claude-sonnet-4-5-stub",
        usage=SimpleNamespace(input_tokens=12, output_tokens=34),
    )

    class _StubMessages:
        def create(self, **_kwargs):
            return fake_response

    stub_client = SimpleNamespace(messages=_StubMessages())

    monkeypatch.setattr(anthropic_service, "is_configured", lambda: True)
    monkeypatch.setattr(anthropic_service, "create_client", lambda: stub_client)
    monkeypatch.setattr(
        anthropic_service, "resolve_default_model", lambda: "claude-sonnet-4-5-stub"
    )

    # Act
    router = AnthropicLLMRouter()
    response = await router.generate(system="sys", user="usr")

    # Assert
    assert response.text == "stub-response"
    assert response.model == "claude-sonnet-4-5-stub"
    assert response.tokens_in == 12
    assert response.tokens_out == 34


def test_get_default_router_picks_openai_by_default(monkeypatch) -> None:
    # Arrange — provider explicitly set to openai (the default).
    from app import runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "get_setting",
        lambda key, default=None: "openai" if key == "COUNCIL_LLM_PROVIDER" else default,
    )

    # Act
    router = get_default_router()

    # Assert
    assert isinstance(router, OpenAILLMRouter)


def test_get_default_router_picks_anthropic_when_configured(monkeypatch) -> None:
    # Arrange — operator opted into Claude.
    from app import runtime_settings

    monkeypatch.setattr(
        runtime_settings,
        "get_setting",
        lambda key, default=None: "anthropic" if key == "COUNCIL_LLM_PROVIDER" else default,
    )

    # Act
    router = get_default_router()

    # Assert
    assert isinstance(router, AnthropicLLMRouter)
