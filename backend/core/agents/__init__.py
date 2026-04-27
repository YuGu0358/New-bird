"""AI Council framework — persona-driven investment analysis.

Public API:
    Persona, SignalWeights, KeyFactor, PersonaResponse
    AnalysisContext, ContextBuilder, PriceSnapshot, NewsItem,
        SocialSignalSnapshot, PositionSnapshot
    LLMRouter, OpenAILLMRouter, LLMResponse, LLMRouterError, LLMRouterUnavailableError
    Analyzer, AnalyzerParseError
    BUILTIN_PERSONAS, PERSONA_INDEX, get_persona, list_personas
"""
from __future__ import annotations

from core.agents.analyzer import Analyzer, AnalyzerParseError
from core.agents.base import KeyFactor, Persona, PersonaResponse, SignalWeights
from core.agents.context import (
    AnalysisContext,
    ContextBuilder,
    NewsItem,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
)
from core.agents.llm_router import (
    LLMResponse,
    LLMRouter,
    LLMRouterError,
    LLMRouterUnavailableError,
    OpenAILLMRouter,
)
from core.agents.personas import (
    BUILTIN_PERSONAS,
    PERSONA_INDEX,
    get_persona,
    list_personas,
)

__all__ = [
    "AnalysisContext",
    "Analyzer",
    "AnalyzerParseError",
    "BUILTIN_PERSONAS",
    "ContextBuilder",
    "KeyFactor",
    "LLMResponse",
    "LLMRouter",
    "LLMRouterError",
    "LLMRouterUnavailableError",
    "NewsItem",
    "OpenAILLMRouter",
    "PERSONA_INDEX",
    "Persona",
    "PersonaResponse",
    "PositionSnapshot",
    "PriceSnapshot",
    "SignalWeights",
    "SocialSignalSnapshot",
    "get_persona",
    "list_personas",
]
