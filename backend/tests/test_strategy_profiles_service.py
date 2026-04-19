from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models import StrategyExecutionParameters, StrategyPreviewRequest, StrategySaveRequest
from app.services import strategy_profiles_service


class StrategyProfilesServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "strategy-tests.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.temp_dir.cleanup()

    def test_fallback_strategy_analysis_extracts_symbols(self) -> None:
        draft = strategy_profiles_service._fallback_strategy_analysis(  # noqa: SLF001
            "关注 NVDA、MSFT 和 AAPL，价格回撤时分批买入。"
        )

        self.assertEqual(draft.parameters.universe_symbols[:3], ["NVDA", "MSFT", "AAPL"])
        self.assertFalse(draft.used_openai)
        self.assertIn("回退模式", draft.normalized_strategy)

    def test_normalize_parameters_uses_sectors_and_exclusions(self) -> None:
        normalized = strategy_profiles_service._normalize_parameters(  # noqa: SLF001
            StrategyExecutionParameters(
                universe_symbols=[],
                preferred_sectors=["technology", "semiconductors"],
                excluded_symbols=["NVDA", "MSFT"],
                entry_drop_percent=2.0,
                add_on_drop_percent=2.0,
                initial_buy_notional=1000.0,
                add_on_buy_notional=100.0,
                max_daily_entries=4,
                max_add_ons=3,
                take_profit_target=80.0,
                stop_loss_percent=12.0,
                max_hold_days=30,
            )
        )

        self.assertIn("AAPL", normalized.universe_symbols)
        self.assertNotIn("NVDA", normalized.universe_symbols)
        self.assertNotIn("MSFT", normalized.universe_symbols)
        self.assertEqual(normalized.max_daily_entries, 4)

    async def test_analyze_strategy_accepts_uploaded_reference_materials(self) -> None:
        with patch("app.services.strategy_profiles_service.openai_service.is_configured", return_value=False):
            draft = await strategy_profiles_service.analyze_strategy(
                "",
                [
                    {
                        "name": "strategy-context.md",
                        "content": "关注 NVDA 和 MSFT，回撤 3% 入场，止损 9%，最长持有 20 天。",
                    }
                ],
            )

        self.assertEqual(draft.source_documents, ["strategy-context.md"])
        self.assertIn("参考上传材料", draft.execution_notes[0])
        self.assertIn("NVDA", draft.parameters.universe_symbols)

    async def test_analyze_factor_code_strategy_uses_static_fallback(self) -> None:
        code = """
factor_name = "volume_momentum"

def alpha(df):
    score = df["close"].pct_change(20) * df["volume"].rolling(5).mean()
    buy_signal = score > 0
    return score.rank(ascending=False)
"""

        with patch("app.services.strategy_profiles_service.openai_service.is_configured", return_value=False):
            draft = await strategy_profiles_service.analyze_factor_code_strategy(
                code,
                description="优先观察 NVDA 和 MSFT，单笔金额保持保守。",
                source_name="volume_momentum.py",
            )

        self.assertEqual(draft.source_documents, ["volume_momentum.py"])
        self.assertIsNotNone(draft.factor_analysis)
        self.assertEqual(draft.factor_analysis.source_name, "volume_momentum.py")
        self.assertIn("volume_momentum", draft.suggested_name)
        self.assertIn("NVDA", draft.parameters.universe_symbols)
        self.assertIn("不能直接运行原始 QuantBrain 因子", " ".join(draft.risk_warnings))
        self.assertFalse(draft.used_openai)

    async def test_save_strategy_enforces_max_five_profiles(self) -> None:
        async with self.session_factory() as session:
            for index in range(5):
                payload = self._build_request(name=f"策略 {index + 1}", activate=index == 0)
                library = await strategy_profiles_service.save_strategy(session, payload)
                self.assertEqual(len(library["items"]), index + 1)

            with self.assertRaisesRegex(ValueError, "最多只能保存 5 套策略"):
                await strategy_profiles_service.save_strategy(
                    session,
                    self._build_request(name="策略 6", activate=False),
                )

    async def test_activate_strategy_switches_active_profile(self) -> None:
        async with self.session_factory() as session:
            first = await strategy_profiles_service.save_strategy(
                session,
                self._build_request(name="成长回撤策略", activate=True),
            )
            first_id = first["active_strategy_id"]

            second = await strategy_profiles_service.save_strategy(
                session,
                self._build_request(name="防守型策略", activate=False),
            )
            second_id = next(
                item["id"]
                for item in second["items"]
                if item["name"] == "防守型策略"
            )

            updated = await strategy_profiles_service.activate_strategy(session, second_id)
            self.assertEqual(updated["active_strategy_id"], second_id)
            self.assertNotEqual(updated["active_strategy_id"], first_id)

            active_item = next(item for item in updated["items"] if item["id"] == second_id)
            inactive_item = next(item for item in updated["items"] if item["id"] == first_id)
            self.assertTrue(active_item["is_active"])
            self.assertFalse(inactive_item["is_active"])

    async def test_update_strategy_rewrites_existing_profile(self) -> None:
        async with self.session_factory() as session:
            saved = await strategy_profiles_service.save_strategy(
                session,
                self._build_request(name="成长回撤策略", activate=True),
            )
            strategy_id = saved["active_strategy_id"]

            updated_library = await strategy_profiles_service.update_strategy(
                session,
                strategy_id,
                self._build_request(name="新版成长策略", activate=True),
            )

            self.assertEqual(len(updated_library["items"]), 1)
            updated_item = updated_library["items"][0]
            self.assertEqual(updated_item["name"], "新版成长策略")
            self.assertEqual(updated_item["id"], strategy_id)
            self.assertTrue(updated_item["is_active"])

    async def test_preview_strategy_summarizes_capital_and_limits(self) -> None:
        with patch(
            "app.services.strategy_profiles_service.monitoring_service.fetch_trend_snapshots",
            AsyncMock(
                return_value={
                    "NVDA": {
                        "day_change_percent": -3.5,
                        "week_change_percent": -5.0,
                        "month_change_percent": 2.0,
                    },
                    "MSFT": {
                        "day_change_percent": -1.2,
                        "week_change_percent": -2.0,
                        "month_change_percent": 4.0,
                    },
                }
            ),
        ):
            preview = await strategy_profiles_service.preview_strategy(
                StrategyPreviewRequest(
                    normalized_strategy="聚焦科技股回撤买入。",
                    parameters=StrategyExecutionParameters(
                        universe_symbols=["NVDA", "MSFT", "AAPL"],
                        preferred_sectors=["technology"],
                        excluded_symbols=["AAPL"],
                        entry_drop_percent=3.0,
                        add_on_drop_percent=2.0,
                        initial_buy_notional=1500.0,
                        add_on_buy_notional=200.0,
                        max_daily_entries=2,
                        max_add_ons=2,
                        take_profit_target=120.0,
                        stop_loss_percent=9.0,
                        max_hold_days=20,
                    ),
                )
            )

        self.assertEqual(preview["universe_size"], 2)
        self.assertEqual(preview["sample_symbols"], ["NVDA", "MSFT"])
        self.assertEqual(preview["likely_trade_symbols"][0], "NVDA")
        self.assertEqual(preview["likely_trade_candidates"][0]["symbol"], "NVDA")
        self.assertIn("达到入场阈值", preview["likely_trade_candidates"][0]["note"])
        self.assertEqual(preview["max_new_positions_per_day"], 2)
        self.assertEqual(preview["max_capital_per_symbol"], 1900.0)
        self.assertEqual(preview["max_new_capital_per_day"], 3000.0)
        self.assertEqual(preview["max_total_capital_if_fully_scaled"], 3800.0)
        self.assertIn("3.0%", preview["entry_trigger_summary"])

    def _build_request(self, *, name: str, activate: bool) -> StrategySaveRequest:
        return StrategySaveRequest(
            name=name,
            original_description="关注 NVDA 和 MSFT，当跌幅扩大时分批买入。",
            normalized_strategy="聚焦 NVDA 和 MSFT，按固定回撤、止盈、止损和持有天数执行。",
            improvement_points=["明确了资金管理规则。"],
            risk_warnings=["不支持做空和期权。"],
            execution_notes=["新的策略会在机器人下次启动时生效。"],
            parameters=StrategyExecutionParameters(
                universe_symbols=["NVDA", "MSFT"],
                preferred_sectors=["technology"],
                excluded_symbols=[],
                entry_drop_percent=2.5,
                add_on_drop_percent=2.0,
                initial_buy_notional=1200.0,
                add_on_buy_notional=150.0,
                max_daily_entries=3,
                max_add_ons=2,
                take_profit_target=100.0,
                stop_loss_percent=10.0,
                max_hold_days=20,
            ),
            activate=activate,
        )


if __name__ == "__main__":
    unittest.main()
