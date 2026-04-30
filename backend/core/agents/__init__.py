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
from core.agents.base import ActionPlan, KeyFactor, Persona, PersonaResponse, SignalWeights
from core.agents.context import (
    AnalysisContext,
    ContextBuilder,
    MarketRegime,
    NewsItem,
    OptionsFlowSnapshot,
    PositionSnapshot,
    PriceSnapshot,
    SocialSignalSnapshot,
    TechnicalsSnapshot,
    VolumeProfile,
)
from core.agents.llm_router import (
    AnthropicLLMRouter,
    LLMResponse,
    LLMRouter,
    LLMRouterError,
    LLMRouterUnavailableError,
    OpenAILLMRouter,
    get_default_router,
)
from core.agents.personas import (
    BUILTIN_PERSONAS,
    PERSONA_INDEX,
    get_persona,
    list_personas,
)

__all__ = [
    "ActionPlan",
    "AnalysisContext",
    "Analyzer",
    "AnalyzerParseError",
    "AnthropicLLMRouter",
    "BUILTIN_PERSONAS",
    "ContextBuilder",
    "KeyFactor",
    "LLMResponse",
    "LLMRouter",
    "LLMRouterError",
    "LLMRouterUnavailableError",
    "MarketRegime",
    "NewsItem",
    "OpenAILLMRouter",
    "OptionsFlowSnapshot",
    "PERSONA_INDEX",
    "Persona",
    "PersonaResponse",
    "PositionSnapshot",
    "PriceSnapshot",
    "SignalWeights",
    "SocialSignalSnapshot",
    "TechnicalsSnapshot",
    "VolumeProfile",
    "get_default_router",
    "get_persona",
    "list_personas",
]
