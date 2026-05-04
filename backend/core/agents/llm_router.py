"""LLM router — abstract single-shot text completion + concrete OpenAI driver.

Stays thin on purpose. Streaming, tool calling, and multi-turn chat are
NOT in scope; we are doing one structured JSON request per analysis.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMRouterError(RuntimeError):
    """Generic LLM call failure (network, parsing, rate limit)."""


class LLMRouterUnavailableError(LLMRouterError):
    """Raised when no provider is configured (e.g. no OPENAI_API_KEY)."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    tokens_in: Optional[int] = None
    tokens_out: Optional[int] = None


class LLMRouter(ABC):
    """Abstract single-shot text generator.

    Concrete implementations call the chosen provider with the supplied
    system + user prompt and return the raw text (expected to be JSON
    when the system prompt asks for it; the analyzer parses).
    """

    @abstractmethod
    async def generate(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Generate a single response. Raise LLMRouterError on failure."""


class OpenAILLMRouter(LLMRouter):
    """OpenAI driver. Uses gpt-4o-mini by default for cost; bump to gpt-4o
    via the `model` arg when accuracy matters more than latency.

    Reads the API key from `runtime_settings.get_setting('OPENAI_API_KEY')`.
    """

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, *, default_model: Optional[str] = None) -> None:
        self._default_model = default_model or self.DEFAULT_MODEL

    async def generate(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
    ) -> LLMResponse:
        api_key = self._resolve_api_key()
        if not api_key:
            raise LLMRouterUnavailableError(
                "OPENAI_API_KEY is not configured. Set it under Settings."
            )

        # Lazy import so test code that monkeypatches doesn't need the
        # SDK installed.
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise LLMRouterError(f"openai SDK not installed: {exc}") from exc

        client = AsyncOpenAI(api_key=api_key)
        model_id = model or self._default_model

        try:
            completion = await client.chat.completions.create(
                model=model_id,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.4,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMRouterError(f"OpenAI call failed: {exc}") from exc

        choice = completion.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise LLMRouterError("OpenAI returned empty content")

        usage = getattr(completion, "usage", None)
        return LLMResponse(
            text=text,
            model=completion.model or model_id,
            tokens_in=getattr(usage, "prompt_tokens", None),
            tokens_out=getattr(usage, "completion_tokens", None),
        )

    @staticmethod
    def _resolve_api_key() -> Optional[str]:
        # Lazy import to avoid a circular dep at module load.
        from app import runtime_settings

        return runtime_settings.get_setting("OPENAI_API_KEY")


class AnthropicLLMRouter(LLMRouter):
    """Anthropic driver. Uses Claude Sonnet 4.5 by default — faster + cheaper
    than Opus for the structured-JSON council prompt. Override with the
    `model` arg or via the `ANTHROPIC_COUNCIL_MODEL` runtime setting.

    Reads the API key from `runtime_settings.get_setting('ANTHROPIC_API_KEY')`.
    """

    # Hard cap on Claude reply length — generous enough for full council JSON
    # but bounded so a runaway response can't burn through the credit pool.
    MAX_TOKENS = 4096

    def __init__(self, *, default_model: Optional[str] = None) -> None:
        self._default_model_override = default_model

    async def generate(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
    ) -> LLMResponse:
        # Lazy import so unit tests that monkeypatch the service don't need
        # the SDK installed and so backend boot tolerates a missing package.
        from app.services import anthropic_service

        if not anthropic_service.is_configured():
            raise LLMRouterUnavailableError(
                "ANTHROPIC_API_KEY is not configured. Set it under Settings."
            )

        try:
            client = anthropic_service.create_client()
        except RuntimeError as exc:
            raise LLMRouterError(str(exc)) from exc

        model_id = (
            model
            or self._default_model_override
            or anthropic_service.resolve_default_model()
        )

        try:
            # Anthropic SDK is sync; offload to the default thread pool so
            # we don't block the event loop in the request path.
            import asyncio

            response = await asyncio.to_thread(
                client.messages.create,
                model=model_id,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=self.MAX_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMRouterError(f"Anthropic call failed: {exc}") from exc

        text = self._extract_text(response)
        if not text.strip():
            raise LLMRouterError("Anthropic returned empty content")

        usage = getattr(response, "usage", None)
        return LLMResponse(
            text=text,
            model=getattr(response, "model", model_id) or model_id,
            tokens_in=getattr(usage, "input_tokens", None),
            tokens_out=getattr(usage, "output_tokens", None),
        )

    @staticmethod
    def _extract_text(response) -> str:
        """Pull the first text block out of an Anthropic Messages response.

        The SDK returns `content` as a list of typed blocks; for our
        single-shot prompts we expect exactly one TextBlock.
        """
        content = getattr(response, "content", None) or []
        for block in content:
            text = getattr(block, "text", None)
            if isinstance(text, str) and text:
                return text
        return ""


def get_default_router() -> LLMRouter:
    """Pick a router from runtime settings; default to OpenAI for backwards compat.

    Set `COUNCIL_LLM_PROVIDER` to "anthropic" to route the council through
    Claude. Any other value (including unset) keeps the existing OpenAI path.
    """
    # Lazy import to avoid a circular dep at module load.
    from app import runtime_settings

    provider = runtime_settings.get_setting("COUNCIL_LLM_PROVIDER", "openai") or "openai"
    if provider.strip().lower() == "anthropic":
        return AnthropicLLMRouter()
    return OpenAILLMRouter()
