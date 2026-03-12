from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from strategy.strategy_b import StrategyBEngine, StrategyExecutionConfig


class StrategyEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_max_daily_entries_blocks_second_new_position(self) -> None:
        engine = StrategyBEngine(
            StrategyExecutionConfig(
                universe=["NVDA", "MSFT"],
                entry_drop_threshold=0.02,
                add_on_drop_threshold=0.02,
                initial_buy_notional=1000.0,
                add_on_buy_notional=100.0,
                max_daily_entries=1,
                max_add_ons=3,
                take_profit_target=80.0,
                stop_loss_threshold=0.12,
                max_hold_days=30,
                strategy_name="测试策略",
            )
        )

        submit_order = AsyncMock(return_value={"status": "accepted"})
        with patch("strategy.strategy_b.alpaca_service.submit_order", submit_order):
            await engine.process_tick(
                symbol="NVDA",
                current_price=97.0,
                previous_close=100.0,
                timestamp=datetime(2026, 3, 12, 10, 0, tzinfo=timezone.utc),
            )
            await engine.process_tick(
                symbol="MSFT",
                current_price=194.0,
                previous_close=200.0,
                timestamp=datetime(2026, 3, 12, 11, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(submit_order.await_count, 1)
        self.assertIn("NVDA", engine.daily_entry_symbols[datetime(2026, 3, 12, tzinfo=timezone.utc).date()])


if __name__ == "__main__":
    unittest.main()
