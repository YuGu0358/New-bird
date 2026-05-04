"""Fundamental valuation engines: DCF + PE-channel.

Pure-python algorithms — no FastAPI / DB / network coupling. The
`app/services/valuation_service.py` adapter pulls live inputs from yfinance
and calls these.
"""
from __future__ import annotations

from core.valuation.dcf import DCFInputs, DCFOutput, run_dcf
from core.valuation.pe_channel import PEChannelOutput, compute_pe_channel

__all__ = [
    "DCFInputs",
    "DCFOutput",
    "PEChannelOutput",
    "compute_pe_channel",
    "run_dcf",
]
