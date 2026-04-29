"""ORM table definitions. Imported for side effects via app.db.engine.init_database()."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.engine import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    entry_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    exit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    net_profit: Mapped[float] = mapped_column(Float, nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(32), nullable=False)


class NewsCache(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="Tavily")


class WatchlistSymbol(Base):
    __tablename__ = "watchlist_symbols"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class PriceAlertRule(Base):
    __tablename__ = "price_alert_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    order_notional_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_change_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class CandidatePoolItem(Base):
    __tablename__ = "candidate_pool_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    snapshot_date: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class SocialSearchCache(Base):
    __tablename__ = "social_search_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cache_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class StrategyProfile(Base):
    __tablename__ = "strategy_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_strategy: Mapped[str] = mapped_column(Text, nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    improvement_points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_warnings_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_notes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SocialSignalSnapshot(Base):
    __tablename__ = "social_signal_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    query_profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    social_score: Mapped[float] = mapped_column(Float, nullable=False)
    market_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_weight: Mapped[float] = mapped_column(Float, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_label: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    top_posts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    top_sources_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_order_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    execution_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False)
    universe_json: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[str] = mapped_column(String(10), nullable=False)
    end_date: Mapped[str] = mapped_column(String(10), nullable=False)
    initial_cash: Mapped[float] = mapped_column(Float, nullable=False)
    final_cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    final_equity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    metrics_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    equity_curve_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BacktestTrade(Base):
    __tablename__ = "backtest_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    notional: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class RiskPolicyConfig(Base):
    """Singleton row: id=1 holds the active policy configuration JSON."""

    __tablename__ = "risk_policy_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RiskEvent(Base):
    """Audit log: each rejected order produces one row here."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    policy_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # "deny" | "allow"
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)


class AgentAnalysis(Base):
    """One persisted analysis per (persona, symbol, timestamp)."""

    __tablename__ = "agent_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    persona_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    reasoning_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    key_factors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    follow_up_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    context_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class UserStrategy(Base):
    """User-uploaded Python strategy code, persisted + reloaded on boot."""

    __tablename__ = "user_strategies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slot_name: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(96), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active|disabled|failed
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MacroThresholdOverride(Base):
    """Per-indicator threshold customization.

    Stored as JSON to mirror the same shape as the seed `default_thresholds`
    so the threshold engine can read either source identically. Sparse —
    only indicators the user has actually overridden have a row.
    """

    __tablename__ = "macro_threshold_overrides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    indicator_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    thresholds_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class BrokerAccount(Base):
    """A broker account the user has connected (alpaca / ibkr / kraken).

    Multi-account: one user may have multiple accounts at the same
    broker (e.g., paper + live, or different IBKR sub-accounts). The
    `(broker, account_id)` pair is the natural key — uniqueness enforced
    via a composite UNIQUE constraint.

    Tier: a user-controlled label that the UI uses to group accounts
    (Tier 1 = primary trading, Tier 2 = secondary, Tier 3 = experimental
    / paper). Defaults to TIER_2 when the user adds an account without
    explicit tier choice.
    """
    __tablename__ = "broker_accounts"
    __table_args__ = (
        UniqueConstraint("broker", "account_id", name="uq_broker_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    broker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="TIER_2")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class JournalEntry(Base):
    """User-authored investment journal entry (markdown body + symbol tags + mood).

    `mood` is stored as a plain string; the service layer enforces the
    enum (bullish|bearish|neutral|watching). Same convention as other
    enum-like string columns in this module (e.g.
    `SocialSignalSnapshot.action`) — keeps the DB schema flexible.
    """

    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    symbols: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mood: Mapped[str] = mapped_column(String(16), nullable=False, default="neutral")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
