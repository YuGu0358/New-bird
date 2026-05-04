"""Anthropic SDK wrapper.

Mirrors the shape of openai_service.py: thin client constructor + a
configuration probe + a model-name resolver. All settings come through
runtime_settings so deployer-supplied keys take precedence over .env,
matching the rest of the project.

Kept deliberately small — the actual prompt/parse logic lives in
core/agents/llm_router.py::AnthropicLLMRouter.
"""
from __future__ import annotations

from app import runtime_settings


# Claude Sonnet 4.5 — current generation, faster + cheaper than Opus for
# the structured-JSON council use case. Override via runtime setting
# ANTHROPIC_COUNCIL_MODEL.
DEFAULT_COUNCIL_MODEL = "claude-sonnet-4-5-20250929"


def is_configured() -> bool:
    """True when an Anthropic API key is present in runtime settings or env."""
    return bool(runtime_settings.get_setting("ANTHROPIC_API_KEY", ""))


def create_client():
    """Construct an Anthropic SDK client.

    Lazy-imports the SDK so a missing module surfaces only at call time —
    backend boot must not fail just because the package is absent in some
    minimal install.
    """
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise RuntimeError("anthropic is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_API_KEY is missing. Configure it in the settings page or backend/.env first.",
    )

    return Anthropic(api_key=api_key)


def resolve_default_model() -> str:
    """Return the configured council model name, falling back to the default."""
    value = runtime_settings.get_setting(
        "ANTHROPIC_COUNCIL_MODEL", DEFAULT_COUNCIL_MODEL
    )
    return value or DEFAULT_COUNCIL_MODEL
