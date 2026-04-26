"""Social signal scoring service package.

Re-exports the legacy public API plus the private helpers that pre-existing
tests import via attribute access on the shim module.
"""
from __future__ import annotations

# Constants
from app.services.social_signal.local_models import (
    DEFAULT_SOCIAL_LANG,
    DEFAULT_SOCIAL_LOOKBACK_HOURS,
    DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES,
    DEFAULT_SOCIAL_POST_LIMIT,
    MAX_SOCIAL_EXECUTIONS_PER_DAY,
    MARKET_CLOSE_HOUR,
    MARKET_OPEN_HOUR,
    MARKET_OPEN_MINUTE,
    SOCIAL_SIGNAL_COOLDOWN,
    SocialSignalQueryProfile,
    SocialTextClassification,
)

# Public API
from app.services.social_signal.persistence import build_query_profile
from app.services.social_signal.runner import (
    get_latest_signals,
    run_social_monitor,
    score_symbol_signal,
)
from app.services.social_signal.scoring import is_market_session_open

# Private helpers re-exported for tests
from app.services.social_signal.classify import (
    _classify_posts,
    _classify_sources,
    _classify_text,
    _local_classify_text,
    _openai_classify_text_sync,
)
from app.services.social_signal.persistence import (
    _ensure_social_auto_trade_allowed,
    _execute_signal_if_allowed,
    _load_positions_map,
    _load_signal_context_symbols,
)
from app.services.social_signal.scoring import (
    _aggregate_social_score,
    _classify_confidence_label,
    _compute_market_score,
    _compute_news_adjustment,
    _downgrade_action,
    _map_action,
    _serialize_snapshot,
)

__all__ = [
    "DEFAULT_SOCIAL_LANG",
    "DEFAULT_SOCIAL_LOOKBACK_HOURS",
    "DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES",
    "DEFAULT_SOCIAL_POST_LIMIT",
    "MARKET_CLOSE_HOUR",
    "MARKET_OPEN_HOUR",
    "MARKET_OPEN_MINUTE",
    "MAX_SOCIAL_EXECUTIONS_PER_DAY",
    "SOCIAL_SIGNAL_COOLDOWN",
    "SocialSignalQueryProfile",
    "SocialTextClassification",
    "build_query_profile",
    "get_latest_signals",
    "is_market_session_open",
    "run_social_monitor",
    "score_symbol_signal",
]
