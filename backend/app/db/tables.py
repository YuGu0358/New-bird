"""ORM table definitions. Imported for side effects via app.db.engine.init_database()."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Index, Integer, JSON, LargeBinary, String, Text, UniqueConstraint
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
    # action_plan_json holds the structured ActionPlan (entry zone, stop, target,
    # time horizon, trigger). Empty {} when the persona declined to give a plan.
    action_plan_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
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


class PositionOverride(Base):
    """User-set per-position annotations stacked on top of broker positions.

    Identified by (broker_account_id, ticker). The UNIQUE constraint
    on that pair makes the table a "key/value lookup with extra fields"
    — the API layer treats it as upsert (PUT replaces an existing row,
    no separate POST/PATCH split).

    All fields except ids and ticker are nullable: the user may set
    just a stop, just a TP, just a note, etc., without forcing the
    others. `tier_override` is a single-position override on top of
    the BrokerAccount.tier — when None, the parent account's tier
    applies.

    NOT a foreign key to BrokerAccount.id at the DB level: SQLite
    enforces FKs only with PRAGMA foreign_keys=ON which the existing
    DB layer doesn't enable. Service layer validates by lookup.
    """
    __tablename__ = "position_overrides"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id", "ticker", name="uq_position_override"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    broker_account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier_override: Mapped[str | None] = mapped_column(String(16), nullable=True)
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


class PositionCost(Base):
    """Per-(broker_account, ticker) cost basis + user-set protective levels.

    A buy event UPSERTs the row by recomputing avg_cost from the old
    aggregate plus the new fill. Sells reduce shares; we keep the same
    avg_cost (FIFO is out of scope for the MVP).
    """

    __tablename__ = "position_costs"
    __table_args__ = (
        UniqueConstraint("broker_account_id", "ticker", name="uq_position_costs_account_ticker"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    broker_account_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    ticker: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    avg_cost_basis: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_shares: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    custom_stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    custom_take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
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


class PositionSnapshot(Base):
    """Periodic snapshot of broker positions (append-only time series).

    Designed for the multi-account portfolio drill-down (Phase 2.5):
    "show me how my AAPL position evolved over the last week" boils
    down to filtering this table by (broker_account_id, symbol) and
    reading the last N rows.

    The composite index on (broker_account_id, symbol, snapshot_at)
    matches the most common query shape — the engine can serve a
    drill-down chart without a sort step.

    Append-only: we never UPDATE rows; the scheduled job inserts a new
    snapshot every 5 minutes for every (account, symbol) pair that has
    an open position. Old snapshots can be aged out via a future
    retention job (out of scope for this task).
    """
    __tablename__ = "position_snapshots"
    __table_args__ = (
        Index(
            "ix_position_snapshots_account_symbol_time",
            "broker_account_id",
            "symbol",
            "snapshot_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    broker_account_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    qty: Mapped[float] = mapped_column(Float, nullable=False)
    avg_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    unrealized_pl: Mapped[float | None] = mapped_column(Float, nullable=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False, default="long")


class UserWorkspace(Base):
    """Saved UI workspace snapshot (active tab, selected ticker, filters, etc.).

    Single-user MVP: no user_id; multi-user is a follow-up.

    The opaque `state_json` blob is stored as Text — the backend doesn't
    interpret the structure, it just round-trips the JSON the frontend
    sends. Names are unique so PUT acts as upsert by name.
    """

    __tablename__ = "user_workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
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


class Workflow(Base):
    """User-built node-graph workflow definition (Phase 5.6).

    The `definition_json` blob stores the React Flow JSON shape verbatim
    (nodes + edges) — same opaque-blob convention as `UserWorkspace`.
    Names are unique so PUT acts as upsert by name.

    `schedule_seconds` is None for run-on-demand workflows. When set
    (>= 60), the application scheduler runs the workflow on that
    interval if `is_active` is True.
    """

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    definition_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    schedule_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
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


class WorkflowRun(Base):
    """Append-only log of paper-order dispatches issued by workflows."""

    __tablename__ = "workflow_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    workflow_name: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    symbol: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    broker: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class SymbolMeta(Base):
    """Static-ish per-symbol metadata for factor mining (sector, industry, market cap).

    Refreshed weekly from yfinance. The `refreshed_at` watermark lets the
    refresh job skip rows that are still inside the freshness window
    (default 7 days), so a daily run only hits yfinance for stale rows.
    """

    __tablename__ = "factor_symbol_meta"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FactorDailyFundamentals(Base):
    """Per-(symbol, date) fundamental snapshot for factor mining.

    Quarterly fundamentals (PE, PB, ROE, etc.) get forward-filled into
    daily rows: a value reported on filing date Y is treated as known
    on every trading day ≥ Y until the next filing supersedes it.
    Daily snapshot fields (market_cap, short_interest_pct) are written
    once per refresh.

    Composite primary key on (symbol, date) — one row per ticker per
    trading day.
    """

    __tablename__ = "factor_daily_fundamentals"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    eps_ttm: Mapped[float | None] = mapped_column(Float, nullable=True)
    revenue_ttm: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    roe: Mapped[float | None] = mapped_column(Float, nullable=True)
    short_interest_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_factor_fund_date", "date"),
    )


class DailyNewsFeatures(Base):
    """Per-(symbol, date) news features used as factor inputs.

    `news_count` is the headline count we collected for the day,
    `sentiment` is an OpenAI-scored aggregate in [-1, +1], and
    `headlines` is a JSON-encoded list of the top 5 headline strings
    so downstream consumers can re-score with a different model
    without re-fetching from Tavily.
    """

    __tablename__ = "factor_daily_news_features"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    news_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sentiment: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    headlines: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
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


class DailyBar(Base):
    """Daily OHLCV bar from Alpaca for the Factor Forge data pipeline.

    Composite primary key on (symbol, date) — one row per ticker per
    trading day. Bars are append-only; in practice we never UPDATE
    because Alpaca's adjusted closes are stable.
    """

    __tablename__ = "factor_daily_bars"

    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("ix_factor_daily_bars_date", "date"),
    )


class DailyActiveUniverse(Base):
    """Per-day top-N most-active universe ranked by composite activity score.

    Composite primary key on (date, rank). rank is 1-based and dense
    within a date. The factor mining pipeline filters bars to this set
    before running operators, so we keep it small (typically 100).
    """

    __tablename__ = "factor_daily_active_universe"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    activity_score: Mapped[float] = mapped_column(Float, nullable=False)
    dollar_volume: Mapped[float] = mapped_column(Float, nullable=False)
    vol_return_score: Mapped[float] = mapped_column(Float, nullable=False)
    range_score: Mapped[float] = mapped_column(Float, nullable=False)


class FactorEvolutionRun(Base):
    """One row per Factor Forge daily evolution run.

    Created in ``running`` state at the start of the pipeline; updated in
    place when the pipeline finishes (``completed``) or aborts
    (``failed``). The ``stats_json`` blob stores the per-stage
    ``GenerationStats`` records as a JSON-serialized dict so the UI can
    show generation-by-generation progress without a separate table.
    """

    __tablename__ = "factor_evolution_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    stage1_best: Mapped[float | None] = mapped_column(Float, nullable=True)
    stage2_best: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_persisted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class FactorRecord(Base):
    """Surviving factor stored in the Factor Forge vector library.

    Holds the formula text plus two embeddings (formula text and
    return-series), used by the dedupe path to reject near-duplicates
    before insertion. Embeddings are persisted as raw float32 bytes via
    ``LargeBinary`` — cheap to read back into a numpy array without a
    JSON parse step.
    """

    __tablename__ = "factor_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    formula: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    fitness: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ic_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    icir: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    formula_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    return_embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quarantined: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FactorPopulationState(Base):
    """Persistent slot-based snapshot of the current GP population.

    One row per slot in the population. Wiped+rewritten at the end of each
    generation so the loop can resume without restarting from scratch.
    """

    __tablename__ = "factor_population_state"

    slot: Mapped[int] = mapped_column(Integer, primary_key=True)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    fitness: Mapped[float] = mapped_column(Float, nullable=False, default=-99.0)
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FactorEvolutionStateSingleton(Base):
    """Holds engine-level state (single row, id=1)."""

    __tablename__ = "factor_evolution_singleton"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    current_generation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    best_fitness_recent: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_generation_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DailyRecommendation(Base):
    """One recommendation row per (date, symbol). Wiped+rewritten daily."""

    __tablename__ = "daily_recommendations"

    date: Mapped[date] = mapped_column(Date, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)  # 'buy' / 'sell' / 'hold'
    entry_low: Mapped[float] = mapped_column(Float, nullable=False)
    entry_high: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    take_profit: Mapped[float] = mapped_column(Float, nullable=False)
    holding_days: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    position_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ensemble_score: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    risk_signals_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rank: Mapped[int] = mapped_column(Integer, nullable=False)  # 1 = strongest buy / sell
    position_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class FactorTrajectory(Base):
    """Trajectory-level evolution record (QuantaAlpha-inspired).

    Each row is one candidate produced by the trajectory loop. Holds the
    LLM's research direction + math intuition + final AST formula plus
    the parent it descended from. Used to render the evolution lineage
    tree on the frontend.
    """

    __tablename__ = "factor_trajectories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    research_direction: Mapped[str] = mapped_column(Text, nullable=False)
    math_intuition: Mapped[str] = mapped_column(Text, nullable=False)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    evolution_step: Mapped[str] = mapped_column(String(32), nullable=False, default="seed")
    fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
    ic_5d: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    factor_record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )


class FactorGenerationStat(Base):
    """Per-generation summary written at the end of each evolution cycle.

    Append-only time series keyed by generation. Powers the history line
    chart in the Factor Forge dashboard (best/median fitness over time).
    """

    __tablename__ = "factor_generation_stats"

    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    best_fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_fitness: Mapped[float | None] = mapped_column(Float, nullable=True)
    persisted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evaluated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class OptionsStructureSnapshot(Base):
    """One captured structure-read at time T, plus its later outcome.

    Captured snapshot rows start with `outcome_status='pending'` and the
    evaluator job fills in the realized fields once `horizon_end_date`
    has arrived and the underlying OHLC for that day is available.

    Composite primary key on (capture_date, ticker, horizon_days) so the
    same ticker can be tracked at multiple horizons in parallel without
    overwriting; one snapshot per (ticker, horizon) per UTC day.
    """

    __tablename__ = "options_structure_snapshots"

    capture_date: Mapped[date] = mapped_column(Date, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    horizon_days: Mapped[int] = mapped_column(Integer, primary_key=True)

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Frozen structure-read at capture time
    pattern: Mapped[str] = mapped_column(String(32), nullable=False)
    winning_player: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signals_fired_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    # Frozen inputs the outcome evaluator needs
    spot_at_capture: Mapped[float] = mapped_column(Float, nullable=False)
    call_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    put_wall: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_pain: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    horizon_end_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Filled by evaluator
    outcome_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", index=True
    )  # pending / hit / miss / no_edge / unevaluable
    realized_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_move_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_metric_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_options_struct_snap_pattern", "pattern"),
    )
