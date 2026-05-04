from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import ibkr_client


def _setting_factory(values: dict[str, str]):
    """Build a fake get_setting that returns the supplied keys, '' otherwise."""

    def _fake_get_setting(key: str, default: str | None = None) -> str | None:
        if key in values:
            return values[key]
        return "" if default == "" else default

    return _fake_get_setting


class GetClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_client_passes_settings_to_connect_async(self) -> None:
        fake_ib = MagicMock()
        fake_ib.connectAsync = AsyncMock(return_value=None)
        fake_ib.disconnect = MagicMock()

        with patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory(
                {
                    "IBKR_HOST": "127.0.0.1",
                    "IBKR_PORT": "4002",
                    "IBKR_CLIENT_ID": "11",
                }
            ),
        ), patch.object(ibkr_client, "IB", return_value=fake_ib):
            async with ibkr_client.get_client() as ib:
                self.assertIs(ib, fake_ib)

        fake_ib.connectAsync.assert_awaited_once_with("127.0.0.1", 4002, clientId=11)
        fake_ib.disconnect.assert_called_once()

    async def test_get_client_disconnects_even_when_body_raises(self) -> None:
        fake_ib = MagicMock()
        fake_ib.connectAsync = AsyncMock(return_value=None)
        fake_ib.disconnect = MagicMock()

        with patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory(
                {
                    "IBKR_HOST": "127.0.0.1",
                    "IBKR_PORT": "4002",
                    "IBKR_CLIENT_ID": "11",
                }
            ),
        ), patch.object(ibkr_client, "IB", return_value=fake_ib):
            with self.assertRaises(RuntimeError):
                async with ibkr_client.get_client():
                    raise RuntimeError("boom")

        fake_ib.connectAsync.assert_awaited_once()
        fake_ib.disconnect.assert_called_once()

    async def test_get_client_raises_config_error_when_settings_missing(self) -> None:
        with patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory({}),
        ):
            with self.assertRaises(ibkr_client.IBKRConfigError):
                async with ibkr_client.get_client():
                    pass


class IsReachableTests(unittest.IsolatedAsyncioTestCase):
    async def test_is_reachable_handles_success_refused_and_timeout(self) -> None:
        settings_patch = patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory(
                {
                    "IBKR_HOST": "127.0.0.1",
                    "IBKR_PORT": "4002",
                    "IBKR_CLIENT_ID": "11",
                }
            ),
        )

        # Success path -> True, and disconnect is still called for cleanup.
        success_ib = MagicMock()
        success_ib.connectAsync = AsyncMock(return_value=None)
        success_ib.disconnect = MagicMock()
        with settings_patch, patch.object(ibkr_client, "IB", return_value=success_ib):
            self.assertTrue(await ibkr_client.is_reachable())
        success_ib.disconnect.assert_called_once()

        # ConnectionRefusedError -> False, no raise.
        refused_ib = MagicMock()
        refused_ib.connectAsync = AsyncMock(side_effect=ConnectionRefusedError())
        refused_ib.disconnect = MagicMock()
        with patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory(
                {
                    "IBKR_HOST": "127.0.0.1",
                    "IBKR_PORT": "4002",
                    "IBKR_CLIENT_ID": "11",
                }
            ),
        ), patch.object(ibkr_client, "IB", return_value=refused_ib):
            self.assertFalse(await ibkr_client.is_reachable())

        # asyncio.TimeoutError -> False, no raise.
        timeout_ib = MagicMock()
        timeout_ib.connectAsync = AsyncMock(side_effect=asyncio.TimeoutError())
        timeout_ib.disconnect = MagicMock()
        with patch.object(
            ibkr_client.runtime_settings,
            "get_setting",
            side_effect=_setting_factory(
                {
                    "IBKR_HOST": "127.0.0.1",
                    "IBKR_PORT": "4002",
                    "IBKR_CLIENT_ID": "11",
                }
            ),
        ), patch.object(ibkr_client, "IB", return_value=timeout_ib):
            self.assertFalse(await ibkr_client.is_reachable())
