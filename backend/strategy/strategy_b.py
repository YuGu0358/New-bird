from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.database import AsyncSessionLocal, Trade
from app.services import alpaca_service

logger = logging.getLogger(__name__)

DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "AMZN",
    "GOOGL",
    "META",
    "NVDA",
    "TSLA",
    "JPM",
    "V",
    "MA",
    "UNH",
    "HD",
    "PG",
    "XOM",
    "KO",
    "PEP",
    "DIS",
    "CRM",
    "NFLX",
    "COST",
]


@dataclass
class StrategyExecutionConfig:
    universe: list[str]
    entry_drop_threshold: float
    add_on_drop_threshold: float
    initial_buy_notional: float
    add_on_buy_notional: float
    max_daily_entries: int
    max_add_ons: int
    take_profit_target: float
    stop_loss_threshold: float
    max_hold_days: int
    strategy_name: str = "系统默认 Strategy B"


@dataclass
class PositionState:
    symbol: str
    entry_date: datetime
    average_entry_price: float
    total_qty: float
    total_cost: float
    add_on_count: int
    last_buy_price: float
    current_price: float
    unrealized_profit: float


@dataclass
class PendingExitState:
    symbol: str
    entry_date: datetime
    entry_price: float
    qty: float
    trigger_price: float
    exit_reason: str
    requested_at: datetime


def build_default_strategy_config() -> StrategyExecutionConfig:
    """Return the built-in Strategy B execution profile."""

    return StrategyExecutionConfig(
        universe=list(DEFAULT_UNIVERSE),
        entry_drop_threshold=0.02,
        add_on_drop_threshold=0.02,
        initial_buy_notional=1000.0,
        add_on_buy_notional=100.0,
        max_daily_entries=3,
        max_add_ons=3,
        take_profit_target=80.0,
        stop_loss_threshold=0.12,
        max_hold_days=30,
    )


class StrategyBEngine:
    """Implements the fixed-notional Strategy B execution rules."""

    def __init__(self, config: StrategyExecutionConfig | None = None) -> None:
        self.config = config or build_default_strategy_config()
        self.positions: dict[str, PositionState] = {}
        self.pending_buy_symbols: set[str] = set()
        self.pending_sell_symbols: set[str] = set()
        self.pending_exit_states: dict[str, PendingExitState] = {}
        self.daily_entry_symbols: dict[date, set[str]] = {}

    def apply_config(self, config: StrategyExecutionConfig) -> None:
        """Swap the active execution profile used for new signals."""

        self.config = config

    async def sync_from_broker(self) -> None:
        """Hydrate in-memory state from Alpaca when the runner restarts.

        The database schema in the PRD only tracks completed trades, so the
        runner rebuilds open positions from the broker. Entry dates reset to
        "now" on restart because there is no dedicated state table.
        """

        try:
            broker_positions = await alpaca_service.list_positions()
        except Exception as exc:
            logger.warning("Skipping broker sync because positions could not be loaded: %s", exc)
            broker_positions = []

        try:
            open_orders = await alpaca_service.list_orders(status="open")
        except Exception as exc:
            logger.warning("Skipping open-order sync because orders could not be loaded: %s", exc)
            open_orders = []

        all_orders: list[dict[str, Any]] = []
        try:
            all_orders = await alpaca_service.list_orders(status="all", limit=200)
        except Exception as exc:
            logger.warning("Skipping order-history sync because orders could not be loaded: %s", exc)

        previous_positions = self.positions
        current_positions: dict[str, PositionState] = {}
        self.pending_buy_symbols = {
            str(order["symbol"]).upper()
            for order in open_orders
            if str(order.get("side", "")).lower() == "buy"
            and str(order.get("symbol", "")).upper() in self.config.universe
        }
        self.pending_sell_symbols = {
            str(order["symbol"]).upper()
            for order in open_orders
            if str(order.get("side", "")).lower() == "sell"
            and str(order.get("symbol", "")).upper() in self.config.universe
        }

        now = datetime.now(timezone.utc)
        for position in broker_positions:
            symbol = position["symbol"].upper()
            if symbol not in self.config.universe:
                continue

            qty = float(position["qty"])
            entry_price = float(position["entry_price"])
            total_cost = qty * entry_price
            current_price = float(position.get("current_price", 0.0) or 0.0)
            unrealized_profit = float(position.get("unrealized_pl", 0.0) or 0.0)
            existing_state = previous_positions.get(symbol)
            add_on_count = int(
                max(
                    0,
                    min(
                        self.config.max_add_ons,
                        round(
                            (total_cost - self.config.initial_buy_notional)
                            / self.config.add_on_buy_notional
                        ),
                    ),
                )
            )
            current_positions[symbol] = PositionState(
                symbol=symbol,
                entry_date=existing_state.entry_date if existing_state is not None else now,
                average_entry_price=entry_price,
                total_qty=qty,
                total_cost=total_cost,
                add_on_count=add_on_count,
                last_buy_price=existing_state.last_buy_price if existing_state is not None else entry_price,
                current_price=current_price,
                unrealized_profit=unrealized_profit,
            )

        self.positions = current_positions
        self._hydrate_daily_entry_symbols(all_orders, now.date())
        await self._finalize_pending_exits(all_orders)

    async def evaluate_broker_positions(self, event_time: datetime | None = None) -> None:
        evaluation_time = event_time or datetime.now(timezone.utc)
        for position in list(self.positions.values()):
            if position.symbol in self.pending_sell_symbols:
                continue

            reference_price = position.current_price if position.current_price > 0 else position.average_entry_price
            await self._evaluate_exit(
                position,
                reference_price,
                evaluation_time,
                current_unrealized_profit=position.unrealized_profit,
            )

    async def process_tick(
        self,
        *,
        symbol: str,
        current_price: float,
        previous_close: float,
        timestamp: datetime | str | None = None,
    ) -> None:
        normalized_symbol = symbol.upper()
        event_time = self._coerce_timestamp(timestamp)

        if normalized_symbol not in self.config.universe:
            return
        if current_price <= 0 or previous_close <= 0:
            return
        if normalized_symbol in self.pending_buy_symbols:
            return
        if normalized_symbol in self.pending_sell_symbols:
            return

        position = self.positions.get(normalized_symbol)
        if position is None:
            daily_drop = (previous_close - current_price) / previous_close
            if daily_drop >= self.config.entry_drop_threshold and self._can_open_new_position(
                normalized_symbol,
                event_time.date(),
            ):
                await self._open_initial_position(normalized_symbol, current_price, event_time)
            return

        if self._can_add_on(position, current_price):
            await self._add_on_position(position, current_price)

        await self._evaluate_exit(position, current_price, event_time)

    def _can_add_on(self, position: PositionState, current_price: float) -> bool:
        if position.add_on_count >= self.config.max_add_ons:
            return False
        trigger_price = position.last_buy_price * (1 - self.config.add_on_drop_threshold)
        return current_price <= trigger_price

    async def _open_initial_position(
        self,
        symbol: str,
        current_price: float,
        event_time: datetime,
    ) -> None:
        if self._estimate_qty(self.config.initial_buy_notional, current_price) <= 0:
            return

        await alpaca_service.submit_order(
            symbol=symbol,
            side="buy",
            notional=self.config.initial_buy_notional,
        )
        self._record_daily_entry(symbol, event_time.date())
        self.pending_buy_symbols.add(symbol)
        logger.info(
            "Submitted initial %s buy order for %s at %.2f",
            self.config.strategy_name,
            symbol,
            current_price,
        )

    async def _add_on_position(self, position: PositionState, current_price: float) -> None:
        if self._estimate_qty(self.config.add_on_buy_notional, current_price) <= 0:
            return

        await alpaca_service.submit_order(
            symbol=position.symbol,
            side="buy",
            notional=self.config.add_on_buy_notional,
        )
        self.pending_buy_symbols.add(position.symbol)

        logger.info(
            "Submitted add-on buy for %s at %.2f",
            position.symbol,
            current_price,
        )

    async def _evaluate_exit(
        self,
        position: PositionState,
        current_price: float,
        event_time: datetime,
        current_unrealized_profit: float | None = None,
    ) -> None:
        unrealized_profit = (
            current_unrealized_profit
            if current_unrealized_profit is not None
            else (current_price - position.average_entry_price) * position.total_qty
        )
        take_profit_hit = unrealized_profit >= self.config.take_profit_target
        stop_loss_hit = unrealized_profit <= -(position.total_cost * self.config.stop_loss_threshold)
        max_hold_hit = event_time - position.entry_date >= timedelta(days=self.config.max_hold_days)

        if not any([take_profit_hit, stop_loss_hit, max_hold_hit]):
            return

        if take_profit_hit:
            exit_reason = "TAKE_PROFIT"
        elif stop_loss_hit:
            exit_reason = "STOP_LOSS"
        else:
            exit_reason = "MAX_HOLD"

        try:
            await alpaca_service.close_position(position.symbol)
        except Exception:
            await alpaca_service.submit_order(
                symbol=position.symbol,
                side="sell",
                qty=round(position.total_qty, 6),
            )

        self.pending_sell_symbols.add(position.symbol)
        self.pending_exit_states[position.symbol] = PendingExitState(
            symbol=position.symbol,
            entry_date=position.entry_date,
            entry_price=position.average_entry_price,
            qty=position.total_qty,
            trigger_price=current_price,
            exit_reason=exit_reason,
            requested_at=event_time,
        )
        logger.info("Submitted exit for %s because %s", position.symbol, exit_reason)

    async def _record_trade(
        self,
        *,
        symbol: str,
        entry_date: datetime,
        entry_price: float,
        exit_price: float,
        qty: float,
        net_profit: float,
        exit_reason: str,
        event_time: datetime,
    ) -> None:
        async with AsyncSessionLocal() as session:
            session.add(
                Trade(
                    symbol=symbol,
                    entry_date=entry_date,
                    exit_date=event_time,
                    entry_price=entry_price,
                    exit_price=exit_price,
                    qty=qty,
                    net_profit=net_profit,
                    exit_reason=exit_reason,
                )
            )
            await session.commit()

    async def _finalize_pending_exits(self, orders: list[dict[str, Any]]) -> None:
        if not self.pending_exit_states:
            return

        open_symbols = set(self.positions)
        still_pending = set(self.pending_sell_symbols)

        for symbol, exit_state in list(self.pending_exit_states.items()):
            if symbol in open_symbols or symbol in still_pending:
                continue

            matched_order = self._find_filled_exit_order(orders, exit_state)
            exit_price = exit_state.trigger_price
            exit_qty = exit_state.qty
            exit_time = exit_state.requested_at

            if matched_order is not None:
                filled_avg_price = matched_order.get("filled_avg_price")
                if filled_avg_price is not None:
                    exit_price = float(filled_avg_price)

                qty = matched_order.get("qty")
                if qty is not None:
                    exit_qty = float(qty)

                created_at = matched_order.get("created_at")
                if isinstance(created_at, datetime):
                    exit_time = created_at

            net_profit = (exit_price - exit_state.entry_price) * exit_qty
            await self._record_trade(
                symbol=exit_state.symbol,
                entry_date=exit_state.entry_date,
                entry_price=exit_state.entry_price,
                exit_price=exit_price,
                qty=exit_qty,
                net_profit=net_profit,
                exit_reason=exit_state.exit_reason,
                event_time=exit_time,
            )
            self.pending_exit_states.pop(symbol, None)
            logger.info("Recorded closed trade for %s because %s", symbol, exit_state.exit_reason)

    @staticmethod
    def _find_filled_exit_order(
        orders: list[dict[str, Any]],
        exit_state: PendingExitState,
    ) -> dict[str, Any] | None:
        matching_orders = [
            order
            for order in orders
            if str(order.get("symbol", "")).upper() == exit_state.symbol
            and str(order.get("side", "")).lower() == "sell"
            and str(order.get("status", "")).lower() == "filled"
        ]
        matching_orders.sort(
            key=lambda order: order.get("created_at") or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        for order in matching_orders:
            created_at = order.get("created_at")
            if isinstance(created_at, datetime) and created_at >= exit_state.requested_at - timedelta(minutes=5):
                return order

        return matching_orders[0] if matching_orders else None

    @staticmethod
    def _estimate_qty(notional: float, price: float) -> float:
        if price <= 0:
            return 0.0
        return round(notional / price, 6)

    def _can_open_new_position(self, symbol: str, current_day: date) -> bool:
        self._prune_daily_entry_cache(current_day)
        tracked_symbols = self.daily_entry_symbols.setdefault(current_day, set())
        if symbol in tracked_symbols:
            return True
        return len(tracked_symbols) < self.config.max_daily_entries

    def _record_daily_entry(self, symbol: str, current_day: date) -> None:
        self._prune_daily_entry_cache(current_day)
        self.daily_entry_symbols.setdefault(current_day, set()).add(symbol)

    def _hydrate_daily_entry_symbols(self, orders: list[dict[str, Any]], current_day: date) -> None:
        tracked_symbols = {
            str(order.get("symbol", "")).upper()
            for order in orders
            if str(order.get("side", "")).lower() == "buy"
            and isinstance(order.get("created_at"), datetime)
            and order["created_at"].date() == current_day
            and str(order.get("symbol", "")).upper() in self.config.universe
        }
        self.daily_entry_symbols = {current_day: tracked_symbols}

    def _prune_daily_entry_cache(self, current_day: date) -> None:
        self.daily_entry_symbols = {
            day: symbols
            for day, symbols in self.daily_entry_symbols.items()
            if day == current_day
        }

    @staticmethod
    def _coerce_timestamp(value: datetime | str | None) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc)
