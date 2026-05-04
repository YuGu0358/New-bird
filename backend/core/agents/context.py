"""AnalysisContext value object + ContextBuilder ABC.

The analyzer hands one of these to the LLM as a structured JSON block.
Building one requires reading our concrete data services (alpaca,
polygon, social_signal, etc.); that lives in app/services/agents_service.py.
This module only defines the shape and the abstract contract.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
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
class TechnicalsSnapshot:
    """Standard technical indicator values at the latest bar.

    Each value is the LAST non-None entry of the indicator series, or
    None if the indicator couldn't be computed (e.g., not enough bars).
    """

    rsi_14: Optional[float] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    sma_20: Optional[float] = None
    ema_20: Optional[float] = None
    bbands_upper: Optional[float] = None
    bbands_middle: Optional[float] = None
    bbands_lower: Optional[float] = None
    bbands_position: Optional[float] = None  # 0..1; where price sits in the band


@dataclass(frozen=True)
class VolumeProfile:
    """Today's tape activity vs. its 20-day baseline."""

    today_volume: Optional[int] = None
    avg_volume_20d: Optional[float] = None
    today_vs_avg_x: Optional[float] = None
    turnover_pct: Optional[float] = None  # today_volume / shares_outstanding * 100


@dataclass(frozen=True)
class OptionsFlowSnapshot:
    """Options chain summary — sourced from options_chain_service."""

    call_wall: Optional[float] = None
    put_wall: Optional[float] = None
    zero_gamma: Optional[float] = None
    max_pain: Optional[float] = None
    total_gex_dollar: Optional[float] = None
    put_call_oi_ratio: Optional[float] = None
    atm_iv: Optional[float] = None


@dataclass(frozen=True)
class MarketRegime:
    """How the symbol's sector + the macro backdrop are positioned."""

    sector: Optional[str] = None
    sector_5d_change_pct: Optional[float] = None
    sector_rank_among_11: Optional[int] = None  # 1 = strongest of 11 GICS
    macro_tags: list[str] = field(default_factory=list)


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
    # Phase A enrichments — optional; LLM is told null=no data available.
    technicals: Optional[TechnicalsSnapshot] = None
    volume_profile: Optional[VolumeProfile] = None
    options_flow: Optional[OptionsFlowSnapshot] = None
    regime: Optional[MarketRegime] = None

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
            "technicals": asdict(self.technicals) if self.technicals is not None else None,
            "volume_profile": asdict(self.volume_profile) if self.volume_profile is not None else None,
            "options_flow": asdict(self.options_flow) if self.options_flow is not None else None,
            "regime": asdict(self.regime) if self.regime is not None else None,
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
