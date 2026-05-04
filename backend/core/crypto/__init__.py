"""Crypto market-data primitives — pure compute over CoinGecko payloads.

The service layer (`app/services/coingecko_service`) handles the httpx fetch
and 5-minute cache. This package owns the universe-free pure compute:

- `compute.parse_markets_payload`: defensive CoinGecko `/coins/markets` parser.
- `compute.sort_and_limit`: stable sort + top-N trim with None-last semantics.
"""
from core.crypto.compute import (
    SORTABLE_COLUMNS,
    CryptoMarketRow,
    parse_markets_payload,
    sort_and_limit,
)

__all__ = [
    "SORTABLE_COLUMNS",
    "CryptoMarketRow",
    "parse_markets_payload",
    "sort_and_limit",
]
