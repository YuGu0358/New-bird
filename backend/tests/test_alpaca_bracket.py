from __future__ import annotations
import unittest
from unittest.mock import patch, MagicMock

from app.services import alpaca_service


class AlpacaBracketTests(unittest.IsolatedAsyncioTestCase):
    async def test_bracket_includes_order_class_and_legs(self) -> None:
        captured = {}

        def fake_submit(**kwargs):
            captured.update(kwargs)
            order = MagicMock()
            order.id = "order-1"
            order.symbol = "AAPL"
            order.side = "buy"
            order.status = "accepted"
            return order

        fake_client = MagicMock()
        fake_client.submit_order.side_effect = fake_submit

        with patch("app.services.alpaca_service._create_client", return_value=fake_client):
            result = await alpaca_service.submit_order(
                "AAPL", "buy", qty=10, take_profit_price=180.0, stop_loss_price=150.0
            )

        self.assertEqual(captured["order_class"], "bracket")
        self.assertEqual(captured["take_profit"], {"limit_price": 180.0})
        self.assertEqual(captured["stop_loss"], {"stop_price": 150.0})
        self.assertEqual(result["status"], "accepted")

    async def test_bracket_only_take_profit(self) -> None:
        captured = {}

        def fake_submit(**kwargs):
            captured.update(kwargs)
            order = MagicMock()
            order.id = "order-2"; order.symbol = "AAPL"; order.side = "buy"; order.status = "accepted"
            return order

        fake_client = MagicMock()
        fake_client.submit_order.side_effect = fake_submit

        with patch("app.services.alpaca_service._create_client", return_value=fake_client):
            await alpaca_service.submit_order("AAPL", "buy", qty=5, take_profit_price=200.0)

        self.assertEqual(captured["order_class"], "bracket")
        self.assertEqual(captured["take_profit"], {"limit_price": 200.0})
        self.assertNotIn("stop_loss", captured)

    async def test_plain_order_unchanged(self) -> None:
        captured = {}

        def fake_submit(**kwargs):
            captured.update(kwargs)
            order = MagicMock()
            order.id = "order-3"; order.symbol = "AAPL"; order.side = "buy"; order.status = "accepted"
            return order

        fake_client = MagicMock()
        fake_client.submit_order.side_effect = fake_submit

        with patch("app.services.alpaca_service._create_client", return_value=fake_client):
            await alpaca_service.submit_order("AAPL", "buy", qty=5)

        self.assertNotIn("order_class", captured)
        self.assertNotIn("take_profit", captured)
        self.assertNotIn("stop_loss", captured)

    async def test_bracket_requires_buy(self) -> None:
        with self.assertRaises(ValueError):
            await alpaca_service.submit_order(
                "AAPL", "sell", qty=10, take_profit_price=180.0
            )


if __name__ == "__main__":
    unittest.main()
