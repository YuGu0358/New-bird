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
    CandidatePoolItem,
    NewsCache,
    PriceAlertRule,
    SocialSearchCache,
    SocialSignalSnapshot,
    StrategyProfile,
    Trade,
    WatchlistSymbol,
)

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "CandidatePoolItem",
    "DATA_DIR",
    "DATABASE_FILE",
    "DATABASE_URL",
    "NewsCache",
    "PriceAlertRule",
    "SocialSearchCache",
    "SocialSignalSnapshot",
    "StrategyProfile",
    "Trade",
    "WatchlistSymbol",
    "engine",
    "get_session",
    "init_database",
]
