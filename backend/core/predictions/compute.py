"""Prediction-market data normalisation — pure compute, no I/O.

Parses Polymarket's gamma-api `/markets` payload into a normalized shape so
the service layer doesn't have to know about upstream key names. The
abstraction makes it easy to add Kalshi or other adapters later by giving
them a function that returns the same `PredictionMarket` dataclass.

Polymarket gives multi-outcome markets (e.g., a Senate race with 5
candidates), but for a Bloomberg-style tile view we only need the YES/NO
binary cut. The parser pulls the first two outcomes and exposes them via
`PredictionOutcome` rows so the UI can render `0.62 / 0.38` without doing
the math itself.

Defensive parser — bad payloads return [] rather than raising.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)


SORTABLE_COLUMNS = (
    "volume_usd",
    "liquidity_usd",
    "end_date",
    "yes_price",
)


@dataclass
class PredictionOutcome:
    label: str
    price: float | None  # 0..1, or None if missing


@dataclass
class PredictionMarket:
    id: str
    question: str
    slug: str | None = None
    category: str | None = None
    end_date: str | None = None  # raw ISO from upstream; not parsed
    closed: bool = False
    active: bool = True
    volume_usd: float | None = None
    liquidity_usd: float | None = None
    yes_price: float | None = None  # convenience: outcomes[0].price when label=="Yes"
    outcomes: list[PredictionOutcome] = field(default_factory=list)


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN guard
        return None
    return out


def _coerce_str(value: object) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _parse_outcomes(item: dict) -> list[PredictionOutcome]:
    """Outcomes / outcome prices arrive as JSON-encoded strings on Polymarket.

    Schema of interest: item["outcomes"] = '["Yes","No"]', item["outcomePrices"] = '["0.62","0.38"]'.
    Be lenient: also accept already-parsed lists in case a future endpoint
    changes the encoding.
    """
    raw_labels = item.get("outcomes")
    raw_prices = item.get("outcomePrices")

    labels: list[str] = []
    prices: list[float | None] = []

    if isinstance(raw_labels, str):
        try:
            labels = [str(x) for x in json.loads(raw_labels)]
        except (ValueError, TypeError):
            labels = []
    elif isinstance(raw_labels, list):
        labels = [str(x) for x in raw_labels]

    if isinstance(raw_prices, str):
        try:
            decoded = json.loads(raw_prices)
            prices = [_coerce_float(x) for x in decoded]
        except (ValueError, TypeError):
            prices = []
    elif isinstance(raw_prices, list):
        prices = [_coerce_float(x) for x in raw_prices]

    if not labels:
        return []

    out: list[PredictionOutcome] = []
    for idx, label in enumerate(labels):
        price = prices[idx] if idx < len(prices) else None
        out.append(PredictionOutcome(label=label, price=price))
    return out


def _parse_one(item: dict) -> PredictionMarket | None:
    market_id = _coerce_str(item.get("id") or item.get("conditionId"))
    question = _coerce_str(item.get("question") or item.get("title"))
    if not market_id or not question:
        return None

    outcomes = _parse_outcomes(item)
    yes_price: float | None = None
    if outcomes and outcomes[0].label.lower() in {"yes", "true"}:
        yes_price = outcomes[0].price

    return PredictionMarket(
        id=market_id,
        question=question,
        slug=_coerce_str(item.get("slug")),
        category=_coerce_str(item.get("category")),
        end_date=_coerce_str(item.get("endDate") or item.get("end_date")),
        closed=bool(item.get("closed")),
        active=bool(item.get("active", True)),
        volume_usd=_coerce_float(item.get("volume") or item.get("volumeNum")),
        liquidity_usd=_coerce_float(item.get("liquidity") or item.get("liquidityNum")),
        yes_price=yes_price,
        outcomes=outcomes,
    )


def parse_markets_payload(items: list[dict]) -> list[PredictionMarket]:
    """Defensive: accepts the gamma-api `/markets` response and yields valid rows.

    Non-dict items + items missing id/question are skipped (logs DEBUG once
    with the total skipped count). Never raises on malformed inputs.
    """
    out: list[PredictionMarket] = []
    skipped = 0
    for item in items:
        if not isinstance(item, dict):
            skipped += 1
            continue
        parsed = _parse_one(item)
        if parsed is None:
            skipped += 1
            continue
        out.append(parsed)
    if skipped:
        logger.debug("Polymarket: skipped %d malformed market(s)", skipped)
    return out


def sort_and_limit(
    rows: list[PredictionMarket],
    *,
    limit: int = 25,
    sort_by: str = "volume_usd",
    descending: bool = True,
) -> list[PredictionMarket]:
    """Stable sort with None values last; tie-break on `id` ascending.

    Allowed sort_by: volume_usd / liquidity_usd / end_date / yes_price.
    Anything else raises ValueError.
    limit clamped to [1, 100].
    """
    if sort_by not in SORTABLE_COLUMNS:
        raise ValueError(
            f"sort_by must be one of {SORTABLE_COLUMNS!r}, got {sort_by!r}"
        )
    capped = max(1, min(int(limit or 0), 100))

    # Split present vs missing so None always sorts last regardless of
    # `descending` direction. Tie-break first, primary second — Python's sort
    # is stable.
    def _value(r: PredictionMarket) -> object:
        return getattr(r, sort_by)

    present = [r for r in rows if _value(r) is not None]
    missing = [r for r in rows if _value(r) is None]

    present = sorted(present, key=lambda r: r.id)
    missing = sorted(missing, key=lambda r: r.id)

    def primary_key(r: PredictionMarket) -> float:
        value = _value(r)
        if isinstance(value, str):
            return float(_string_to_orderable(value))
        return float(value)  # type: ignore[arg-type]

    present.sort(key=primary_key, reverse=descending)
    return (present + missing)[:capped]


def _string_to_orderable(value: str) -> int:
    """Map a string to an integer for sort key compatibility.

    We only sort strings via end_date which is ISO-8601-ish; using the raw
    string compares lexicographically (which is correct for ISO dates).
    Map to a stable integer hash — since ISO strings sort the same way as
    their lexicographic order, we encode each char's code point.
    """
    # Compact: only encode the first 19 chars (YYYY-MM-DDTHH:MM:SS) so sort
    # is well-defined and bounded.
    head = value[:19].ljust(19, " ")
    out = 0
    for c in head:
        out = (out << 8) | (ord(c) & 0xFF)
    return out


def _iter_outcomes(rows: Iterable[PredictionMarket]) -> Iterable[PredictionOutcome]:
    for row in rows:
        yield from row.outcomes
