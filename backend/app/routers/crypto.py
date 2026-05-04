"""Crypto markets endpoint — top-N coins via CoinGecko.

Disabled by default. The setting gate (`CRYPTO_COINGECKO_ENABLED`) is
checked inside the service; when off, the service raises a RuntimeError
mentioning "disabled" which we map to HTTP 503 so the UI can render the
"enable in settings" hint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import service_error
from app.models.crypto import CryptoMarketsResponse
from app.services import coingecko_service

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/markets", response_model=CryptoMarketsResponse)
async def get_markets(
    limit: int = 100,
    sort_by: str = "volume_24h_usd",
    descending: bool = True,
) -> CryptoMarketsResponse:
    """Top-N crypto coins by 24h volume (default), via CoinGecko.

    `limit` is clamped to [1, 250]. `sort_by` accepts: market_cap_usd,
    volume_24h_usd, change_24h_pct, rank, price_usd. Anything else → 400.
    """
    try:
        payload = await coingecko_service.get_markets(
            limit=limit,
            sort_by=sort_by,
            descending=descending,
        )
    except RuntimeError as exc:
        message = str(exc)
        if "disabled" in message.lower():
            raise HTTPException(status_code=503, detail=message) from exc
        raise service_error(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise service_error(exc) from exc
    return CryptoMarketsResponse(**payload)
