"""Pydantic API models, grouped by domain.

Flat re-exports preserve the legacy import path:
    from app.models import Account, MonitoringOverview, ...

Internally, callers may also import from the submodule directly:
    from app.models.account import Account
"""
from __future__ import annotations

from app.models.account import (
    Account,
    BotStatus,
    ControlResponse,
    OrderRecord,
    Position,
    TradeRecord,
)
from app.models.alerts import (
    PriceAlertRuleCreateRequest,
    PriceAlertRuleUpdateRequest,
    PriceAlertRuleView,
)
from app.models.monitoring import (
    AssetUniverseItem,
    CandidatePoolEntry,
    MonitoringOverview,
    TrackedSymbolView,
    TrendSnapshot,
    WatchlistUpdateRequest,
)
from app.models.research import (
    ChartPoint,
    CompanyProfileResponse,
    NewsArticle,
    ResearchSource,
    StockResearchReport,
    SymbolChartResponse,
    TavilySearchResponse,
    TavilySearchSource,
)
from app.models.settings import (
    RuntimeSettingItem,
    RuntimeSettingsStatus,
    SettingsUpdateRequest,
)
from app.models.social import (
    SocialCountBucket,
    SocialPostAuthor,
    SocialPostItem,
    SocialPostMetrics,
    SocialProviderStatus,
    SocialSearchResponse,
    SocialSignalQueryProfile,
    SocialSignalRunRequest,
    SocialSignalRunResponse,
    SocialSignalSnapshotView,
    SocialSignalSource,
)
from app.models.strategies import (
    QuantBrainFactorAnalysis,
    QuantBrainFactorAnalysisRequest,
    RegisteredStrategiesResponse,
    RegisteredStrategyEntry,
    StoredStrategy,
    StrategyAnalysisDraft,
    StrategyAnalysisRequest,
    StrategyExecutionParameters,
    StrategyLibraryResponse,
    StrategyPreviewCandidate,
    StrategyPreviewRequest,
    StrategyPreviewResponse,
    StrategySaveRequest,
)

__all__ = [
    "Account",
    "AssetUniverseItem",
    "BotStatus",
    "CandidatePoolEntry",
    "ChartPoint",
    "CompanyProfileResponse",
    "ControlResponse",
    "MonitoringOverview",
    "NewsArticle",
    "OrderRecord",
    "Position",
    "PriceAlertRuleCreateRequest",
    "PriceAlertRuleUpdateRequest",
    "PriceAlertRuleView",
    "QuantBrainFactorAnalysis",
    "QuantBrainFactorAnalysisRequest",
    "RegisteredStrategiesResponse",
    "RegisteredStrategyEntry",
    "ResearchSource",
    "RuntimeSettingItem",
    "RuntimeSettingsStatus",
    "SettingsUpdateRequest",
    "SocialCountBucket",
    "SocialPostAuthor",
    "SocialPostItem",
    "SocialPostMetrics",
    "SocialProviderStatus",
    "SocialSearchResponse",
    "SocialSignalQueryProfile",
    "SocialSignalRunRequest",
    "SocialSignalRunResponse",
    "SocialSignalSnapshotView",
    "SocialSignalSource",
    "StockResearchReport",
    "StoredStrategy",
    "StrategyAnalysisDraft",
    "StrategyAnalysisRequest",
    "StrategyExecutionParameters",
    "StrategyLibraryResponse",
    "StrategyPreviewCandidate",
    "StrategyPreviewRequest",
    "StrategyPreviewResponse",
    "StrategySaveRequest",
    "SymbolChartResponse",
    "TavilySearchResponse",
    "TavilySearchSource",
    "TradeRecord",
    "TrackedSymbolView",
    "TrendSnapshot",
    "WatchlistUpdateRequest",
]
