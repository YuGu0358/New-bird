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
        ):
            with self.assertRaisesRegex(ValueError, "没有可用公司资料"):
                await company_profile_service.get_company_profile("AAPL")
