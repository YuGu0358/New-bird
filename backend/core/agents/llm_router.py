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
