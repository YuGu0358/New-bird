"""BacktestEngine — drives a Strategy through a stream of historical bars."""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Callable

from core.backtest.broker import BacktestBroker
from core.backtest.metrics import compute_metrics
from core.backtest.portfolio import BacktestPortfolio
from core.backtest.types import Bar, BacktestConfig, BacktestResult
from core.broker.base import Broker
from core.strategy.base import Strategy
from core.strategy.context import StrategyContext

StrategyFactory = Callable[[Broker], Strategy]


class BacktestEngine:
    """Runs a bar-by-bar replay against a Strategy."""

    def __init__(
        self,
        *,
        config: BacktestConfig,
        strategy_factory: StrategyFactory,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config = config
        self._strategy_factory = strategy_factory
        self._logger = logger or logging.getLogger("backtest")

    async def run(self, bars_by_symbol: dict[str, list[Bar]]) -> BacktestResult:
        portfolio = BacktestPortfolio(initial_cash=self.config.initial_cash)

        # Group bars chronologically, interleaving symbols by timestamp.
        merged: list[Bar] = []
        for symbol_bars in bars_by_symbol.values():
            merged.extend(symbol_bars)
        merged.sort(key=lambda b: b.timestamp)

        # Mutable cell so the broker callbacks can read the current sim time
        # and per-symbol prices.
        current_prices: dict[str, float] = {}
        sim_now = {"value": merged[0].timestamp if merged else datetime.now(timezone.utc)}

        broker = BacktestBroker(
            portfolio,
            current_price_provider=lambda s: current_prices.get(s, 0.0),
            current_time_provider=lambda: sim_now["value"],
        )
        strategy = self._strategy_factory(broker)
        ctx = StrategyContext(parameters=strategy.parameters, logger=self._logger)

        started_at = datetime.now(timezone.utc)
        await strategy.on_start(ctx)

        # Stream bars. Each timestamp can carry multiple symbols' bars.
        try:
            grouped: dict[datetime, list[Bar]] = {}
            for bar in merged:
                grouped.setdefault(bar.timestamp, []).append(bar)

            for ts in sorted(grouped):
                sim_now["value"] = ts
                for bar in grouped[ts]:
                    current_prices[bar.symbol] = bar.close

                # Periodic broker sync once per day BEFORE bar evaluation.
                try:
                    await strategy.on_periodic_sync(ctx, ts)
                except Exception:
                    self._logger.exception("Strategy periodic sync raised in backtest")

                for bar in grouped[ts]:
                    if bar.previous_close is None or bar.previous_close <= 0:
                        continue
                    try:
                        await strategy.on_tick(
                            ctx,
                            symbol=bar.symbol,
                            price=bar.close,
                            previous_close=bar.previous_close,
                            timestamp=bar.timestamp,
                        )
                    except Exception:
                        self._logger.exception("Strategy on_tick raised for %s", bar.symbol)

                portfolio.record_equity_snapshot(timestamp=ts, prices=dict(current_prices))
        finally:
            try:
                await strategy.on_stop(ctx)
            except Exception:
                self._logger.exception("Strategy on_stop raised")

        finished_at = datetime.now(timezone.utc)

        # Compute realized PnL per round-trip for win-rate / profit-factor.
        pnl_per_trade = self._extract_pnl_per_trade(portfolio.trades)
        metrics = compute_metrics(portfolio.equity_curve, pnl_per_trade=pnl_per_trade)

        equity_value = portfolio.equity(prices=current_prices)
        return BacktestResult(
            config=self.config,
            started_at=started_at,
            finished_at=finished_at,
            final_cash=portfolio.cash,
            final_equity=equity_value,
            equity_curve=list(portfolio.equity_curve),
            trades=list(portfolio.trades),
            metrics=metrics,
        )

    @staticmethod
    def _extract_pnl_per_trade(trades: Iterable) -> list[float]:
        # FIFO match buys with sells per symbol.
        from collections import deque

        open_lots: dict[str, "deque"] = {}
        pnls: list[float] = []
        for trade in trades:
            if trade.side == "buy":
                open_lots.setdefault(trade.symbol, deque()).append(trade)
            elif trade.side == "sell":
                lots = open_lots.get(trade.symbol)
                if not lots:
                    continue
                # The portfolio always closes the full position (single FIFO chunk).
                cost = sum(lot.notional for lot in lots)
                pnls.append(trade.notional - cost)
                lots.clear()
        return pnls
