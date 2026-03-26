from __future__ import annotations

import unittest

import requests

from app.services import network_utils


class NetworkUtilsTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_sync_with_retries_recovers_from_connection_reset(self) -> None:
        attempts = {"count": 0}

        def flaky_call() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise requests.exceptions.ConnectionError(
                    "Connection aborted.",
                    ConnectionResetError(54, "Connection reset by peer"),
                )
            return "ok"

        result = await network_utils.run_sync_with_retries(flaky_call, attempts=3, delay_seconds=0)

        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 2)

    async def test_run_sync_with_retries_does_not_retry_non_network_error(self) -> None:
        attempts = {"count": 0}

        def broken_call() -> None:
            attempts["count"] += 1
            raise ValueError("bad input")

        with self.assertRaisesRegex(ValueError, "bad input"):
            await network_utils.run_sync_with_retries(broken_call, attempts=3, delay_seconds=0)

        self.assertEqual(attempts["count"], 1)

    def test_friendly_service_error_detail_hides_raw_connection_tuple(self) -> None:
        exc = requests.exceptions.ConnectionError(
            "Connection aborted.",
            ConnectionResetError(54, "Connection reset by peer"),
        )

        detail = network_utils.friendly_service_error_detail(exc)

        self.assertEqual(detail, "外部数据源连接被重置或暂时不可用，请稍后重试。")


if __name__ == "__main__":
    unittest.main()
