"""Daily news feature extraction for the active factor-mining universe.

For each symbol on a target date, we:
  1. Fetch up to 8 headlines via the existing `tavily_service.fetch_raw_headlines`.
  2. Score the aggregate sentiment with OpenAI on a [-1, +1] scale.
  3. Upsert one row into `factor_daily_news_features` per (symbol, date).

The OpenAI call is synchronous, so we wrap it with `asyncio.to_thread`. The
operation is idempotent: re-running for the same (symbol, date) deletes the
prior row before inserting the fresh one, so a partial run can be retried safely.

Note: the original spec referenced `tavily_service.search_company_news`, but the
actual project API is `fetch_raw_headlines(symbol, *, max_results, lang)` which
returns `{"headlines": [{"title": ..., ...}, ...]}`. We adapt to that here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date

from sqlalchemy import delete

from app import runtime_settings
from app.db.engine import AsyncSessionLocal
from app.db.tables import DailyNewsFeatures
from app.services import tavily_service
from app.services.openai_service import create_client

logger = logging.getLogger(__name__)

DEFAULT_MAX_HEADLINES = 8
TOP_N_HEADLINES = 5
DEFAULT_OPENAI_MODEL = "gpt-4o-mini-2024-07-18"


async def _fetch_headlines_for(symbol: str, target_date: date) -> list[str]:
    """Fetch a list of headline strings for ``symbol`` via the existing Tavily wrapper.

    `target_date` is accepted for API symmetry — Tavily's news endpoint already
    biases towards recent items and we keep the daily-job cadence aligned. We
    don't post-filter by date because Tavily's `published_date` field isn't
    always populated, and a same-day-only cut would zero out too many symbols.
    """
    try:
        payload = await tavily_service.fetch_raw_headlines(
            symbol, max_results=DEFAULT_MAX_HEADLINES
        )
    except Exception:
        logger.warning("tavily fetch failed for %s", symbol, exc_info=True)
        return []

    items = []
    if isinstance(payload, dict):
        items = (
            payload.get("headlines")
            or payload.get("results")
            or payload.get("articles")
            or []
        )

    headlines: list[str] = []
    for item in items[:TOP_N_HEADLINES]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("headline") or ""
        title = str(title).strip()
        if title:
            headlines.append(title)
    return headlines


def _parse_sentiment(text: str) -> float:
    """Coerce model output into a clamped float in [-1, 1].

    Robust to chatty replies — searches for the first numeric token if the
    raw text isn't already a bare float.
    """
    cleaned = (text or "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
        value = float(match.group(0)) if match else 0.0
    if value > 1.0:
        return 1.0
    if value < -1.0:
        return -1.0
    return value


def _score_sentiment_sync(headlines: list[str]) -> float:
    """Ask OpenAI to score the aggregated headline sentiment in [-1, +1]."""
    if not headlines:
        return 0.0
    client = create_client()
    model_name = (
        runtime_settings.get_setting("OPENAI_NEWS_MODEL", DEFAULT_OPENAI_MODEL)
        or DEFAULT_OPENAI_MODEL
    )
    prompt = (
        "Rate the aggregate market sentiment of the following headlines on a -1 to +1 scale "
        "(-1 = strongly bearish, 0 = neutral, +1 = strongly bullish). Reply with ONLY a number.\n\n"
        + "\n".join(f"- {h}" for h in headlines)
    )
    response = client.responses.create(
        model=model_name,
        instructions="You are a financial sentiment classifier. Output a single float in [-1, 1].",
        input=[{"role": "user", "content": prompt}],
    )
    text = (getattr(response, "output_text", None) or "").strip()
    return _parse_sentiment(text)


async def update_news_features(symbols: list[str], target_date: date) -> int:
    """Fetch and score news for each symbol on ``target_date``. Idempotent per (symbol, date).

    Returns the number of rows successfully written. A failure for one symbol
    is isolated so it doesn't block the rest of the batch.
    """
    if not symbols:
        return 0

    inserted = 0
    for raw_symbol in symbols:
        if not raw_symbol:
            continue
        sym = raw_symbol.upper()
        headlines = await _fetch_headlines_for(sym, target_date)
        try:
            sentiment = await asyncio.to_thread(_score_sentiment_sync, headlines)
        except Exception:
            logger.warning("sentiment scoring failed for %s", sym, exc_info=True)
            sentiment = 0.0

        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(DailyNewsFeatures).where(
                    DailyNewsFeatures.symbol == sym,
                    DailyNewsFeatures.date == target_date,
                )
            )
            session.add(
                DailyNewsFeatures(
                    symbol=sym,
                    date=target_date,
                    news_count=len(headlines),
                    sentiment=float(sentiment),
                    headlines=json.dumps(headlines, ensure_ascii=False),
                )
            )
            try:
                await session.commit()
                inserted += 1
            except Exception:
                await session.rollback()
                logger.warning(
                    "News upsert failed for %s on %s", sym, target_date, exc_info=True
                )
    return inserted
