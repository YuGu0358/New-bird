"""Mock-based tests for ``app.services.ibkr_service``.

The fake IB instance is a ``MagicMock`` whose lookup methods are sync (``positions``,
``openTrades``, ``placeOrder``) and whose async helpers (``reqCompletedOrdersAsync``,
``reqTickersAsync``) are ``AsyncMock``. No real socket — ``ibkr_client.get_client``
is patched to yield the fake.
"""

from __future__ import annotations

import math
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import ibkr_client, ibkr_service


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #

ACCOUNT_ID = "DU1234567"


def _setting_factory(values: dict[str, str]):
    """Build a fake ``runtime_settings.get_setting`` returning supplied keys."""

    def _fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key in values:
            return values[key]
        return "" if default == "" else default

    return _fake_get_setting


def _fake_account_value(account: str, tag: str, value: str, currency: str = "USD"):
    return SimpleNamespace(account=account, tag=tag, value=value, currency=currency, modelCode="")


def _fake_contract(symbol: str, exchange: str = "SMART", currency: str = "USD"):
    return SimpleNamespace(symbol=symbol, exchange=exchange, currency=currency, secType="STK")


def _fake_position(account: str, symbol: str, qty: float, avg_cost: float):
    return SimpleNamespace(
        account=account,
        contract=_fake_contract(symbol),
        position=qty,
        avgCost=avg_cost,
    )


def _fake_trade(
    *,
    perm_id: int,
    symbol: str,
    action: str,
    qty: float,
    status: str,
    filled_avg_price: float = 0.0,
    submitted_at: datetime | None = None,
):
    order = SimpleNamespace(
        orderId=perm_id,
        permId=perm_id,
        action=action,
        totalQuantity=qty,
        orderType="MKT",
    )
    order_status = SimpleNamespace(
        status=status,
        filled=qty if status == "Filled" else 0.0,
        avgFillPrice=filled_avg_price,
        permId=perm_id,
    )
    log_time = submitted_at or datetime(2026, 4, 27, 14, 0, tzinfo=timezone.utc)
    log = [SimpleNamespace(time=log_time, status="Submitted", message="", errorCode=0)]
    return SimpleNamespace(
        contract=_fake_contract(symbol),
        order=order,
        orderStatus=order_status,
        fills=[],
        log=log,
        advancedError="",
    )


def _patch_settings(values: dict[str, str]):
    return patch.object(
        ibkr_service.runtime_settings,
        "get_setting",
        side_effect=_setting_factory(values),
    )


def _patch_get_client(fake_ib: MagicMock):
    @asynccontextmanager
    async def _fake_get_client():
        yield fake_ib

    return patch.object(ibkr_service, "get_client", _fake_get_client)


# --------------------------------------------------------------------------- #
# get_account                                                                 #
# --------------------------------------------------------------------------- #

class GetAccountTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_account_summary_rows_to_newbird_shape(self) -> None:
        fake_ib = MagicMock()
        fake_ib.accountSummary = MagicMock(
            return_value=[
                _fake_account_value(ACCOUNT_ID, "NetLiquidation", "100000.50"),
                _fake_account_value(ACCOUNT_ID, "BuyingPower", "200000.00"),
                _fake_account_value(ACCOUNT_ID, "TotalCashValue", "50000.25"),
                _fake_account_value(ACCOUNT_ID, "AccountType", "INDIVIDUAL"),
                # extra fields plus a row for another account that should be ignored
                _fake_account_value(ACCOUNT_ID, "Currency", "USD"),
                _fake_account_value("OTHER", "NetLiquidation", "999999.99"),
            ]
        )

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            result = await ibkr_service.get_account()

        self.assertEqual(result["id"], ACCOUNT_ID)
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["currency"], "USD")
        self.assertAlmostEqual(result["equity"], 100000.50)
        self.assertAlmostEqual(result["cash"], 50000.25)
        self.assertAlmostEqual(result["buying_power"], 200000.00)
        self.assertEqual(set(result.keys()), {"id", "status", "currency", "equity", "cash", "buying_power"})

    async def test_raises_config_error_when_account_id_missing(self) -> None:
        fake_ib = MagicMock()
        with _patch_settings({}), _patch_get_client(fake_ib):
            with self.assertRaises(ibkr_client.IBKRConfigError):
                await ibkr_service.get_account()


# --------------------------------------------------------------------------- #
# list_positions                                                              #
# --------------------------------------------------------------------------- #

class ListPositionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_filters_to_configured_account_id(self) -> None:
        fake_ib = MagicMock()
        fake_ib.positions = MagicMock(
            return_value=[
                _fake_position(ACCOUNT_ID, "NVDA", 100.0, 450.0),
                _fake_position(ACCOUNT_ID, "TSLA", -25.0, 220.0),
                _fake_position("OTHER", "AAPL", 1000.0, 150.0),  # filtered out
            ]
        )

        # marketPrice via reqTickersAsync — used to compute current_price/market_value
        async def _req_tickers(*contracts, regulatorySnapshot: bool = False):
            return [SimpleNamespace(marketPrice=lambda c=c: 500.0 if c.symbol == "NVDA" else 210.0)
                    for c in contracts]

        fake_ib.reqTickersAsync = AsyncMock(side_effect=_req_tickers)

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            rows = await ibkr_service.list_positions()

        self.assertEqual(len(rows), 2)
        symbols = {row["symbol"] for row in rows}
        self.assertEqual(symbols, {"NVDA", "TSLA"})

        nvda = next(r for r in rows if r["symbol"] == "NVDA")
        self.assertAlmostEqual(nvda["qty"], 100.0)
        self.assertAlmostEqual(nvda["avg_entry_price"], 450.0)
        self.assertAlmostEqual(nvda["current_price"], 500.0)
        self.assertAlmostEqual(nvda["market_value"], 100.0 * 500.0)
        self.assertAlmostEqual(nvda["unrealized_pl"], 100.0 * (500.0 - 450.0))
        self.assertEqual(nvda["side"], "long")

        tsla = next(r for r in rows if r["symbol"] == "TSLA")
        self.assertEqual(tsla["side"], "short")
        self.assertAlmostEqual(tsla["qty"], -25.0)


# --------------------------------------------------------------------------- #
# list_orders                                                                 #
# --------------------------------------------------------------------------- #

class ListOrdersTests(unittest.IsolatedAsyncioTestCase):
    def _ib_with_orders(self) -> MagicMock:
        fake_ib = MagicMock()
        open_trades = [
            _fake_trade(perm_id=1, symbol="NVDA", action="BUY", qty=10, status="PreSubmitted"),
            _fake_trade(perm_id=2, symbol="TSLA", action="SELL", qty=5, status="Submitted"),
        ]
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        old = datetime.now(timezone.utc) - timedelta(days=30)
        completed = [
            _fake_trade(
                perm_id=3,
                symbol="AAPL",
                action="BUY",
                qty=20,
                status="Filled",
                filled_avg_price=180.0,
                submitted_at=recent,
            ),
            _fake_trade(
                perm_id=4,
                symbol="MSFT",
                action="BUY",
                qty=15,
                status="Filled",
                filled_avg_price=320.0,
                submitted_at=recent,
            ),
            _fake_trade(
                perm_id=5,
                symbol="OLD",
                action="SELL",
                qty=1,
                status="Filled",
                submitted_at=old,
            ),
        ]
        fake_ib.openTrades = MagicMock(return_value=open_trades)
        fake_ib.reqCompletedOrdersAsync = AsyncMock(return_value=completed)
        return fake_ib

    async def test_status_open_returns_only_open_orders(self) -> None:
        fake_ib = self._ib_with_orders()
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            rows = await ibkr_service.list_orders(status="open")

        self.assertEqual({r["symbol"] for r in rows}, {"NVDA", "TSLA"})
        fake_ib.reqCompletedOrdersAsync.assert_not_awaited()

        # check shape
        first = rows[0]
        self.assertEqual(set(first.keys()),
                         {"id", "symbol", "side", "qty", "status", "submitted_at", "filled_avg_price"})
        self.assertIn(first["side"], {"buy", "sell"})

    async def test_status_closed_filters_to_last_seven_days_and_truncates(self) -> None:
        fake_ib = self._ib_with_orders()
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            rows = await ibkr_service.list_orders(status="closed", limit=5)

        # 2 recent completed only — 30-day-old "OLD" must be filtered, open orders excluded
        symbols = {r["symbol"] for r in rows}
        self.assertEqual(symbols, {"AAPL", "MSFT"})
        fake_ib.openTrades.assert_not_called()

    async def test_status_closed_limit_truncates(self) -> None:
        # extend completed list to verify limit truncation
        fake_ib = MagicMock()
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        completed = [
            _fake_trade(
                perm_id=i,
                symbol=f"SYM{i}",
                action="BUY",
                qty=1,
                status="Filled",
                submitted_at=recent,
            )
            for i in range(1, 11)
        ]
        fake_ib.openTrades = MagicMock(return_value=[])
        fake_ib.reqCompletedOrdersAsync = AsyncMock(return_value=completed)

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            rows = await ibkr_service.list_orders(status="closed", limit=3)

        self.assertEqual(len(rows), 3)


# --------------------------------------------------------------------------- #
# submit_order                                                                #
# --------------------------------------------------------------------------- #

class SubmitOrderTests(unittest.IsolatedAsyncioTestCase):
    def _ib_for_submit(self):
        fake_ib = MagicMock()
        # placeOrder is sync and returns a Trade
        def _place_order(contract, order):
            return _fake_trade(
                perm_id=42,
                symbol=contract.symbol,
                action=order.action,
                qty=order.totalQuantity,
                status="Submitted",
            )

        fake_ib.placeOrder = MagicMock(side_effect=_place_order)
        return fake_ib

    async def test_submit_order_qty_buys_with_correct_contract_and_order(self) -> None:
        fake_ib = self._ib_for_submit()
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            result = await ibkr_service.submit_order(symbol="nvda", side="buy", qty=10)

        # placeOrder called once with a NVDA Stock + BUY MarketOrder for 10
        fake_ib.placeOrder.assert_called_once()
        contract, order = fake_ib.placeOrder.call_args.args
        self.assertEqual(contract.symbol, "NVDA")
        self.assertEqual(getattr(contract, "exchange", ""), "SMART")
        self.assertEqual(getattr(contract, "currency", ""), "USD")
        self.assertEqual(order.action, "BUY")
        self.assertAlmostEqual(order.totalQuantity, 10.0)
        # no Limit price
        self.assertEqual(order.orderType, "MKT")

        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(result["side"], "buy")
        self.assertAlmostEqual(result["qty"], 10.0)
        self.assertEqual(set(result.keys()),
                         {"id", "symbol", "side", "qty", "status", "submitted_at"})

    async def test_submit_order_buy_translates_lowercase_to_ibkr_uppercase(self) -> None:
        fake_ib = self._ib_for_submit()
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            await ibkr_service.submit_order(symbol="AAPL", side="buy", qty=1)
        _, order = fake_ib.placeOrder.call_args.args
        self.assertEqual(order.action, "BUY")

        fake_ib.placeOrder.reset_mock()
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            await ibkr_service.submit_order(symbol="AAPL", side="sell", qty=1)
        _, order = fake_ib.placeOrder.call_args.args
        self.assertEqual(order.action, "SELL")

    async def test_submit_order_notional_converts_via_market_price(self) -> None:
        fake_ib = self._ib_for_submit()
        # 5000 / 250 = 20 shares
        fake_ib.reqTickersAsync = AsyncMock(
            return_value=[SimpleNamespace(marketPrice=lambda: 250.0)]
        )

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            result = await ibkr_service.submit_order(symbol="NVDA", side="buy", notional=5000.0)

        _, order = fake_ib.placeOrder.call_args.args
        self.assertAlmostEqual(order.totalQuantity, 20.0)
        self.assertAlmostEqual(result["qty"], 20.0)

    async def test_submit_order_notional_raises_when_market_price_is_nan(self) -> None:
        fake_ib = self._ib_for_submit()
        fake_ib.reqTickersAsync = AsyncMock(
            return_value=[SimpleNamespace(marketPrice=lambda: math.nan)]
        )

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            with self.assertRaises(ValueError) as ctx:
                await ibkr_service.submit_order(symbol="NVDA", side="buy", notional=5000.0)

        self.assertIn("market price unavailable", str(ctx.exception))
        fake_ib.placeOrder.assert_not_called()

    async def test_submit_order_rejects_both_or_neither_qty_and_notional(self) -> None:
        fake_ib = self._ib_for_submit()
        # neither
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            with self.assertRaises(ValueError):
                await ibkr_service.submit_order(symbol="NVDA", side="buy")
        # both
        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            with self.assertRaises(ValueError):
                await ibkr_service.submit_order(symbol="NVDA", side="buy", qty=1, notional=100.0)
        fake_ib.placeOrder.assert_not_called()


# --------------------------------------------------------------------------- #
# close_position                                                              #
# --------------------------------------------------------------------------- #

class ClosePositionTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_position_submits_opposite_sell_market_order(self) -> None:
        fake_ib = MagicMock()
        fake_ib.positions = MagicMock(
            return_value=[
                _fake_position(ACCOUNT_ID, "NVDA", 100.0, 450.0),
            ]
        )
        # for list_positions current-price lookup (not strictly needed by close_position
        # but we set it defensively in case the impl uses positions())
        fake_ib.reqTickersAsync = AsyncMock(
            return_value=[SimpleNamespace(marketPrice=lambda: 500.0)]
        )

        def _place_order(contract, order):
            return _fake_trade(
                perm_id=99,
                symbol=contract.symbol,
                action=order.action,
                qty=order.totalQuantity,
                status="Submitted",
            )

        fake_ib.placeOrder = MagicMock(side_effect=_place_order)

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            result = await ibkr_service.close_position("NVDA")

        contract, order = fake_ib.placeOrder.call_args.args
        self.assertEqual(contract.symbol, "NVDA")
        self.assertEqual(order.action, "SELL")
        self.assertAlmostEqual(order.totalQuantity, 100.0)
        self.assertEqual(result["symbol"], "NVDA")
        self.assertEqual(result["side"], "sell")
        self.assertEqual(set(result.keys()),
                         {"id", "symbol", "side", "qty", "status", "submitted_at"})

    async def test_no_open_position_raises_value_error(self) -> None:
        fake_ib = MagicMock()
        fake_ib.positions = MagicMock(return_value=[])
        fake_ib.placeOrder = MagicMock()

        with _patch_settings({"IBKR_ACCOUNT_ID": ACCOUNT_ID}), _patch_get_client(fake_ib):
            with self.assertRaises(ValueError):
                await ibkr_service.close_position("XYZ")
        fake_ib.placeOrder.assert_not_called()
