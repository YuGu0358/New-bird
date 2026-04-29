"""Database layer: engine + ORM tables.

Re-exports everything callers used to import from app.database, so:
    from app.db import Trade, get_session, init_database, Base
all work.
"""
from __future__ import annotations

from app.db.engine import (
    AsyncSessionLocal,
    Base,
    DATA_DIR,
    DATABASE_FILE,
    DATABASE_URL,
    engine,
    get_session,
    init_database,
)
from app.db.tables import (
    AgentAnalysis,
    BacktestRun,
    BacktestTrade,
    BrokerAccount,
    CandidatePoolItem,
    JournalEntry,
    MacroThresholdOverride,
    NewsCache,
    PositionOverride,
    PriceAlertRule,
    RiskEvent,
    RiskPolicyConfig,
    SocialSearchCache,
    SocialSignalSnapshot,
    StrategyProfile,
    Trade,
    UserStrategy,
    WatchlistSymbol,
)

__all__ = [
    "AgentAnalysis",
    "AsyncSessionLocal",
    "BacktestRun",
    "BacktestTrade",
    "Base",
    "BrokerAccount",
    "CandidatePoolItem",
    "DATA_DIR",
    "DATABASE_FILE",
    "DATABASE_URL",
    "JournalEntry",
    "MacroThresholdOverride",
    "NewsCache",
    "PositionOverride",
    "PriceAlertRule",
    "RiskEvent",
    "RiskPolicyConfig",
    "SocialSearchCache",
    "SocialSignalSnapshot",
    "StrategyProfile",
    "Trade",
    "UserStrategy",
    "WatchlistSymbol",
    "engine",
    "get_session",
    "init_database",
]
