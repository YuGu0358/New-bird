from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import PriceAlertRuleCreateRequest, PriceAlertRuleUpdateRequest
from app.services import price_alerts_service


class PriceAlertsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "alerts-tests.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_create_and_list_rule(self) -> None:
        async with self.session_factory() as session:
            created = await price_alerts_service.create_rule(
                session,
                PriceAlertRuleCreateRequest(
                    symbol="aapl",
                    condition_type="price_above",
                    target_value=200,
                    action_type="email",
                    note="突破就提醒",
                ),
            )

            self.assertEqual(created["symbol"], "AAPL")
            self.assertEqual(created["condition_summary"], "价格涨到 200.00 美元 以上")

            listed = await price_alerts_service.list_rules(session, symbol="AAPL")
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["action_summary"], "触发后发送邮件提醒")

    async def test_evaluate_rules_once_triggers_email_and_disables_rule(self) -> None:
        async with self.session_factory() as session:
            await price_alerts_service.create_rule(
                session,
                PriceAlertRuleCreateRequest(
                    symbol="NVDA",
                    condition_type="day_change_up",
                    target_value=5,
                    action_type="email",
                    note="拉升超过 5%",
                ),
            )

        with patch(
            "app.services.price_alerts_service.alpaca_service.get_market_snapshots",
            AsyncMock(
                return_value={
                    "NVDA": {
                        "price": 210.0,
                        "previous_close": 200.0,
                    }
                }
            ),
        ), patch(
            "app.services.price_alerts_service.email_service.send_price_alert_email",
            AsyncMock(),
        ) as send_email_mock:
            triggered = await price_alerts_service.evaluate_rules_once(self.session_factory)

        self.assertEqual(triggered, 1)
        self.assertEqual(send_email_mock.await_count, 1)

        async with self.session_factory() as session:
            listed = await price_alerts_service.list_rules(session, symbol="NVDA")
            self.assertEqual(len(listed), 1)
            self.assertFalse(listed[0]["enabled"])
            self.assertEqual(listed[0]["action_result"], "已发送邮件提醒。")
            self.assertEqual(listed[0]["trigger_change_percent"], 5.0)

    async def test_update_rule_rearms_triggered_rule(self) -> None:
        async with self.session_factory() as session:
            created = await price_alerts_service.create_rule(
                session,
                PriceAlertRuleCreateRequest(
                    symbol="MSFT",
                    condition_type="price_below",
                    target_value=300,
                    action_type="email",
                ),
            )
            rule_id = created["id"]
            await price_alerts_service.update_rule(
                session,
                rule_id,
                PriceAlertRuleUpdateRequest(enabled=False),
            )
            rearmed = await price_alerts_service.update_rule(
                session,
                rule_id,
                PriceAlertRuleUpdateRequest(enabled=True),
            )

        self.assertTrue(rearmed["enabled"])
        self.assertIsNone(rearmed["triggered_at"])
        self.assertEqual(rearmed["action_result"], "")

    def test_auto_trade_guard_blocks_live_by_default(self) -> None:
        with patch(
            "app.services.price_alerts_service.runtime_settings.get_setting",
            return_value="https://api.alpaca.markets",
        ), patch(
            "app.services.price_alerts_service.runtime_settings.get_bool_setting",
            return_value=False,
        ):
            with self.assertRaisesRegex(RuntimeError, "paper 账户"):
                price_alerts_service._ensure_auto_trade_allowed()  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
