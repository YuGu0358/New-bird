"""Backward-compat shim. New code should import from app.services.social_signal directly."""
from app.services.social_signal import *  # noqa: F401, F403
from app.services.social_signal import (  # noqa: F401
    _aggregate_social_score,
    _classify_confidence_label,
    _classify_posts,
    _classify_sources,
    _classify_text,
    _compute_market_score,
    _compute_news_adjustment,
    _downgrade_action,
    _ensure_social_auto_trade_allowed,
    _execute_signal_if_allowed,
    _load_positions_map,
    _load_signal_context_symbols,
    _local_classify_text,
    _map_action,
    _openai_classify_text_sync,
    _serialize_snapshot,
    __all__,
)
