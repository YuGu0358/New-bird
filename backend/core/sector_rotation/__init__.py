"""Sector rotation — compute helpers + sector universe.

Pure-compute layer: turns daily close-price series into 1d / 5d / 1m / 3m / YTD
returns and per-window ranks. The service layer (`app/services/sector_rotation_service`)
handles the yfinance fetch.
"""
from core.sector_rotation.universe import SECTOR_ETFS, SectorETF
from core.sector_rotation.compute import (
    RETURN_WINDOWS,
    SectorRow,
    SectorSnapshot,
    compute_rotation,
    compute_returns,
)

__all__ = [
    "RETURN_WINDOWS",
    "SECTOR_ETFS",
    "SectorETF",
    "SectorRow",
    "SectorSnapshot",
    "compute_returns",
    "compute_rotation",
]
