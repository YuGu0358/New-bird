"""AnalysisContext value object + ContextBuilder ABC.

The analyzer hands one of these to the LLM as a structured JSON block.
Building one requires reading our concrete data services (alpaca,
polygon, social_signal, etc.); that lives in app/services/agents_service.py.
This module only defines the shape and the abstract contract.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class PriceSnapshot:
    last: float
    previous_close: float
    change_pct: float  # since previous close
    week_change_pct: float
    month_change_pct: float
    year_change_pct: float


@dataclass(frozen=True)
class NewsItem:
    title: str
    summary: str
    source: str
    at: datetime


@dataclass(frozen=True)
class SocialSignalSnapshot:
    """A read of P5's social-signal pipeline at the time of analysis."""

    social_score: float  # in [-1, 1]
    market_score: float  # in [-1, 1]
    final_weight: float  # in [-1, 1]
    action: str  # "buy" | "sell" | "hold" | "avoid"
    confidence_label: str  # "low" | "medium" | "high"
    reasons: list[str]


@dataclass(frozen=True)
class PositionSnapshot:
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True)
class AnalysisContext:
    """Everything the analyzer hands to the LLM, in one bundle."""

    symbol: str
    question: Optional[str]
    price: PriceSnapshot
    fundamentals: dict[str, object]
    recent_news: list[NewsItem]
    social: Optional[SocialSignalSnapshot]
    position: Optional[PositionSnapshot]
    generated_at: datetime

    def to_json_block(self) -> str:
        """Serialize to a stable JSON string for embedding in prompts."""
        payload: dict[str, object] = {
            "symbol": self.symbol,
            "question": self.question,
            "generated_at": self.generated_at.isoformat(),
            "price": asdict(self.price),
            "fundamentals": dict(self.fundamentals or {}),
            "recent_news": [
                {
                    "title": n.title,
                    "summary": n.summary,
                    "source": n.source,
                    "at": n.at.isoformat(),
                }
                for n in self.recent_news
            ],
            "social": asdict(self.social) if self.social is not None else None,
            "position": asdict(self.position) if self.position is not None else None,
        }
        return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


class ContextBuilder(ABC):
    """Interface every concrete context builder implements.

    Concrete impls live outside `core/`. The framework only depends on
    the shape, not on alpaca/polygon/etc.
    """

    @abstractmethod
    async def build(self, symbol: str, *, question: Optional[str] = None) -> AnalysisContext:
        """Gather all evidence for `symbol` and assemble an AnalysisContext."""
