"""Broker account tier vocabulary.

Used by the BrokerAccount table + service + Pydantic enum. Centralised
here so a UI dropdown / future audit log don't drift from the database
constraint.
"""
from __future__ import annotations

from typing import Literal

TIER_1 = "TIER_1"
TIER_2 = "TIER_2"
TIER_3 = "TIER_3"

ALL_TIERS = (TIER_1, TIER_2, TIER_3)

TierLiteral = Literal["TIER_1", "TIER_2", "TIER_3"]


def is_valid_tier(value: str) -> bool:
    return value in ALL_TIERS
