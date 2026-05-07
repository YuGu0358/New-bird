"""AI Council framework — persona-driven investment analysis.

Public API:
    Persona, SignalWeights, KeyFactor, PersonaResponse
    AnalysisContext, ContextBuilder, PriceSnapshot, NewsItem,
        SocialSignalSnapshot, PositionSnapshot
    LLMRouter, OpenAILLMRouter, LLMResponse, LLMRouterError, LLMRouterUnavailableError
    Analyzer, AnalyzerParseError
    BUILTIN_PERSONAS, PERSONA_INDEX, get_persona, list_personas

Research-flavored extensions (sector / theme / earnings review):
    MarketResearchReport, EarningsReview, PeerRow, PeerComps,
        IdeaShortlistItem, VarianceRow, GuidanceChange, FilingHighlight
    ResearchAnalyzer, ResearchAnalyzerParseError
    MARKET_RESEARCHER_PERSONA, EARNINGS_REVIEWER_PERSONA,
        RESEARCH_PERSONAS, RESEARCH_PERSONA_INDEX,
        get_research_persona, list_research_personas
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
from core.agents.research_analyzer import (
    ResearchAnalyzer,
    ResearchAnalyzerParseError,
)
from core.agents.research_personas import (
    EARNINGS_REVIEWER_PERSONA,
    MARKET_RESEARCHER_PERSONA,
    RESEARCH_PERSONA_INDEX,
    RESEARCH_PERSONAS,
    get_research_persona,
    list_research_personas,
)
from core.agents.research_schemas import (
    EarningsReview,
    FilingHighlight,
    GuidanceChange,
    IdeaShortlistItem,
    MarketResearchReport,
    PeerComps,
    PeerRow,
    VarianceRow,
)

__all__ = [
    "ActionPlan",
    "AnalysisContext",
    "Analyzer",
    "AnalyzerParseError",
    "AnthropicLLMRouter",
    "BUILTIN_PERSONAS",
    "ContextBuilder",
    "EARNINGS_REVIEWER_PERSONA",
    "EarningsReview",
    "FilingHighlight",
    "GuidanceChange",
    "IdeaShortlistItem",
    "KeyFactor",
    "LLMResponse",
    "LLMRouter",
    "LLMRouterError",
    "LLMRouterUnavailableError",
    "MARKET_RESEARCHER_PERSONA",
    "MarketRegime",
    "MarketResearchReport",
    "NewsItem",
    "OpenAILLMRouter",
    "OptionsFlowSnapshot",
    "PERSONA_INDEX",
    "PeerComps",
    "PeerRow",
    "Persona",
    "PersonaResponse",
    "PositionSnapshot",
    "PriceSnapshot",
    "RESEARCH_PERSONAS",
    "RESEARCH_PERSONA_INDEX",
    "ResearchAnalyzer",
    "ResearchAnalyzerParseError",
    "SignalWeights",
    "SocialSignalSnapshot",
    "TechnicalsSnapshot",
    "VarianceRow",
    "VolumeProfile",
    "get_default_router",
    "get_persona",
    "get_research_persona",
    "list_personas",
    "list_research_personas",
]
