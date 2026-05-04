from __future__ import annotations

import unittest
from unittest.mock import patch

from app.services import company_profile_service


class CompanyProfileServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        company_profile_service._profile_cache.clear()  # noqa: SLF001

    async def test_get_company_profile_maps_yfinance_fields(self) -> None:
        profile_info = {
            "longName": "NVIDIA Corporation",
            "fullExchangeName": "NasdaqGS",
            "quoteType": "EQUITY",
            "sector": "Technology",
            "industry": "Semiconductors",
            "website": "https://www.nvidia.com",
            "currency": "USD",
            "marketCap": 3_100_000_000_000,
            "fullTimeEmployees": 29600,
            "city": "Santa Clara",
            "state": "CA",
            "country": "United States",
            "longBusinessSummary": "Designs GPUs and AI computing platforms.",
        }

        with patch(
            "app.services.company_profile_service._download_company_info_sync",
            return_value=profile_info,
        ) as download_mock:
            payload = await company_profile_service.get_company_profile("nvda")

        download_mock.assert_called_once_with("NVDA")
        self.assertEqual(payload["symbol"], "NVDA")
        self.assertEqual(payload["company_name"], "NVIDIA Corporation")
        self.assertEqual(payload["exchange"], "NasdaqGS")
        self.assertEqual(payload["sector"], "Technology")
        self.assertEqual(payload["industry"], "Semiconductors")
        self.assertEqual(payload["market_cap"], 3_100_000_000_000.0)
        self.assertEqual(payload["full_time_employees"], 29600)
        self.assertEqual(payload["location"], "Santa Clara, CA, United States")
        self.assertEqual(payload["business_summary"], "Designs GPUs and AI computing platforms.")

    async def test_get_company_profile_rejects_empty_profile(self) -> None:
        with patch(
            "app.services.company_profile_service._download_company_info_sync",
            return_value={},
        ), patch(
            "app.services.company_profile_service._download_company_search_sync",
            return_value={},
        ):
            with self.assertRaisesRegex(ValueError, "没有可用公司资料"):
                await company_profile_service.get_company_profile("AAPL")

    async def test_get_company_profile_falls_back_when_yfinance_is_unauthorized(self) -> None:
        # Default language is English, so the fallback text should mention
        # "unauthorized" (English) rather than "未授权" (Chinese).
        with patch(
            "app.services.company_profile_service._download_company_info_sync",
            side_effect=Exception("HTTP Error 401: Unauthorized"),
        ), patch(
            "app.services.company_profile_service._download_company_search_sync",
            return_value={
                "longName": "Apple Inc.",
                "shortName": "Apple Inc.",
                "fullExchangeName": "NASDAQ",
                "quoteType": "EQUITY",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "_profile_fallback": True,
            },
        ):
            payload = await company_profile_service.get_company_profile("AAPL")

        self.assertEqual(payload["company_name"], "Apple Inc.")
        self.assertEqual(payload["exchange"], "NASDAQ")
        self.assertEqual(payload["sector"], "Technology")
        self.assertIn("unauthorized", payload["business_summary"].lower())
        self.assertNotIn("HTTP Error 401", payload["business_summary"])

    async def test_get_company_profile_unauthorized_fallback_localized_to_chinese(self) -> None:
        # When the caller asks for Chinese the same fallback should render in
        # Chinese (the i18n pivot — keep the historical 未授权 string alive
        # for zh users).
        company_profile_service._profile_cache.clear()  # noqa: SLF001
        with patch(
            "app.services.company_profile_service._download_company_info_sync",
            side_effect=Exception("HTTP Error 401: Unauthorized"),
        ), patch(
            "app.services.company_profile_service._download_company_search_sync",
            return_value={
                "longName": "Apple Inc.",
                "shortName": "Apple Inc.",
                "fullExchangeName": "NASDAQ",
                "quoteType": "EQUITY",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "_profile_fallback": True,
            },
        ):
            payload = await company_profile_service.get_company_profile("AAPL", lang="zh")

        self.assertIn("未授权", payload["business_summary"])
        self.assertNotIn("HTTP Error 401", payload["business_summary"])

    async def test_get_company_profile_prefers_search_for_plain_crypto_symbols(self) -> None:
        with patch(
            "app.services.company_profile_service._download_company_search_sync",
            return_value={
                "longName": "Bitcoin USD",
                "shortName": "Bitcoin USD",
                "fullExchangeName": "CCC",
                "quoteType": "CRYPTOCURRENCY",
                "_profile_fallback": True,
            },
        ) as search_mock, patch(
            "app.services.company_profile_service._download_company_info_sync",
            return_value={
                "longName": "Grayscale Bitcoin Mini Trust ETF",
                "quoteType": "ETF",
            },
        ) as info_mock:
            payload = await company_profile_service.get_company_profile("BTC")

        search_mock.assert_called_once_with("BTC")
        info_mock.assert_not_called()
        self.assertEqual(payload["company_name"], "Bitcoin USD")
        self.assertEqual(payload["quote_type"], "CRYPTOCURRENCY")

    async def test_get_company_profile_returns_friendly_error_when_all_sources_fail(self) -> None:
        with patch(
            "app.services.company_profile_service._download_company_info_sync",
            side_effect=Exception("HTTP Error 401: Unauthorized"),
        ), patch(
            "app.services.company_profile_service._download_company_search_sync",
            return_value={},
        ):
            with self.assertRaisesRegex(ValueError, "公司资料源暂时不可用"):
                await company_profile_service.get_company_profile("AAPL")

    def test_search_profile_accepts_crypto_alias_symbol(self) -> None:
        payload = company_profile_service._build_search_profile(  # noqa: SLF001
            "HYPE",
            [
                {
                    "symbol": "HYPE32196-USD",
                    "shortname": "Hyperliquid USD",
                    "quoteType": "CRYPTOCURRENCY",
                    "exchange": "CCC",
                    "exchDisp": "CCC",
                }
            ],
        )

        self.assertEqual(payload["shortName"], "Hyperliquid USD")
        self.assertEqual(payload["quoteType"], "CRYPTOCURRENCY")
        self.assertTrue(payload["_profile_fallback"])
