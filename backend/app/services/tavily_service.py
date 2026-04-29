from __future__ import annotations
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app import runtime_settings
from app.services.network_utils import run_sync_with_retries
from core.i18n import DEFAULT_LANG, language_name, normalize_lang

logger = logging.getLogger(__name__)

_SEARCH_CACHE_TTL = timedelta(minutes=20)
# Cache key now includes the target language so en/zh/de/fr each get their own
# row — Tavily answers are localised in-place so we must not return a Chinese
# summary to an English caller (or vice versa).
_search_cache: dict[tuple[str, str, str], tuple[datetime, dict[str, Any]]] = {}


def _create_client():
    try:
        from tavily import TavilyClient
    except ImportError as exc:
        raise RuntimeError("tavily-python is not installed.") from exc

    api_key = runtime_settings.get_required_setting(
        "TAVILY_API_KEY",
        "Tavily API key is missing. Configure it in the settings page or backend/.env first.",
    )

    return TavilyClient(api_key=api_key)


def _localize_text(text: str, lang: str, *, kind: str = "summary") -> str:
    """Translate `text` into the target language using OpenAI as a best-effort.

    Returns the original text unchanged when:
    - `lang` is English (no translation needed),
    - text is empty,
    - OpenAI is not configured / quota exhausted / any other failure.

    `kind` is a short label that shows up in the system prompt so the model
    keeps the register right (news, headline, search-answer, etc.).
    """
    text = (text or "").strip()
    if not text:
        return text
    target = normalize_lang(lang)
    if target == "en":
        return text

    try:
        from app.services.openai_service import create_client, is_configured
    except Exception:  # noqa: BLE001
        return text
    if not is_configured():
        return text

    target_name = language_name(target)
    system = (
        "You are a precise financial-news translator. Translate the user-provided "
        f"{kind} into {target_name}. Preserve all numbers, tickers, percentages, and proper "
        "names exactly. Keep tone professional and concise. Return ONLY the translated text — "
        "no preamble, no quotes."
    )

    try:
        client = create_client()
        model_name = (
            runtime_settings.get_setting("OPENAI_TRANSLATION_MODEL", "gpt-4o-mini")
            or "gpt-4o-mini"
        )
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        translated = (response.choices[0].message.content or "").strip()
        return translated or text
    except Exception as exc:  # noqa: BLE001
        logger.debug("translation to %s failed (kind=%s): %s", target, kind, exc)
        return text


def _normalize_topic(topic: str | None) -> str:
    normalized = str(topic or "news").strip().lower()
    if normalized not in {"news", "general"}:
        raise ValueError("topic 仅支持 news 或 general。")
    return normalized


def _normalize_result(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    url = str(item.get("url", "")).strip()
    if not url:
        return None

    content = str(item.get("content", "")).strip().replace("\n", " ")
    return {
        "title": str(item.get("title", "")).strip() or url,
        "url": url,
        "content": content[:280].strip(),
        "source": str(item.get("source", "")).strip() or None,
        "domain": str(item.get("domain", "")).strip() or None,
        "published_date": str(item.get("published_date", "")).strip() or None,
        "score": float(item.get("score", 0.0) or 0.0),
    }


_EMPTY_ANSWER_FALLBACKS: dict[str, str] = {
    "en": "Tavily search completed, but no summary is available right now. Query: {q}",
    "zh": "已完成 Tavily 搜索，但当前没有返回可直接展示的摘要。关键词：{q}",
    "de": "Tavily-Suche abgeschlossen, aber derzeit liegt keine Zusammenfassung vor. Suchbegriff: {q}",
    "fr": "Recherche Tavily terminée, mais aucun résumé n'est disponible pour le moment. Requête : {q}",
}

_NO_NEWS_FALLBACKS: dict[str, str] = {
    "en": "No material headlines were returned for {symbol}. Re-run the query later or inspect the raw news feed.",
    "zh": "{symbol} 暂未返回有重要影响的新闻，请稍后再试或直接查看原始新闻源。",
    "de": "Für {symbol} wurden keine marktrelevanten Schlagzeilen geliefert. Versuche es später erneut oder prüfe die Rohnachrichten.",
    "fr": "Aucune actualité majeure n'a été retournée pour {symbol}. Réessaie plus tard ou consulte le flux d'actualités brut.",
}


async def search_web(
    query: str,
    topic: str = "news",
    max_results: int = 6,
    *,
    lang: str = DEFAULT_LANG,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("搜索关键词不能为空。")

    normalized_topic = _normalize_topic(topic)
    target_lang = normalize_lang(lang)
    cache_key = (normalized_query.lower(), normalized_topic, target_lang)
    now = datetime.now(timezone.utc)
    cached_item = _search_cache.get(cache_key)
    if cached_item is not None and now - cached_item[0] <= _SEARCH_CACHE_TTL:
        return cached_item[1]

    client = _create_client()
    response = await run_sync_with_retries(
        client.search,
        query=normalized_query,
        topic=normalized_topic,
        search_depth="advanced",
        max_results=max(1, min(int(max_results), 8)),
        include_answer=True,
    )

    answer = ""
    results: list[dict[str, Any]] = []
    if isinstance(response, dict):
        answer = str(response.get("answer", "")).strip()
        results = [
            normalized_item
            for normalized_item in (
                _normalize_result(item) for item in (response.get("results") or [])
            )
            if normalized_item is not None
        ]

    if not answer:
        fallback_template = _EMPTY_ANSWER_FALLBACKS.get(
            target_lang, _EMPTY_ANSWER_FALLBACKS["en"]
        )
        answer = fallback_template.format(q=normalized_query)
    else:
        answer = _localize_text(answer, target_lang, kind="search summary")

    payload = {
        "query": normalized_query,
        "topic": normalized_topic,
        "answer": answer,
        "generated_at": now,
        "results": results,
    }
    _search_cache[cache_key] = (now, payload)
    return payload


async def fetch_raw_headlines(
    symbol: str,
    *,
    max_results: int = 10,
    lang: str = DEFAULT_LANG,
) -> dict[str, Any]:
    """Tavily news results without LLM summarization.

    Distinct from `fetch_news_summary` — that one routes the headlines through
    an OpenAI-style summary so the UI gets one paragraph. This one returns the
    individual articles with title / url / source / domain / published_date /
    snippet, so the user can scan the raw feed without paying for the summary
    pass and without language localization. Tavily's `include_answer=False`
    flag keeps the response light.

    Caches per (symbol, max_results) — language is irrelevant here because we
    don't translate any of the per-article fields. The 20-min TTL matches
    `search_web` so a watchlist refresh doesn't churn the upstream.
    """
    normalized_symbol = symbol.upper()
    capped = max(1, min(int(max_results or 0), 20))
    cache_key = (f"raw:{normalized_symbol}", "news", f"k={capped}")
    now = datetime.now(timezone.utc)
    cached_item = _search_cache.get(cache_key)
    if cached_item is not None and now - cached_item[0] <= _SEARCH_CACHE_TTL:
        return cached_item[1]

    client = _create_client()
    response = await run_sync_with_retries(
        client.search,
        query=f"latest news headlines about {normalized_symbol} stock",
        topic="news",
        search_depth="basic",
        max_results=capped,
        include_answer=False,
    )

    results: list[dict[str, Any]] = []
    if isinstance(response, dict):
        results = [
            normalized_item
            for normalized_item in (
                _normalize_result(item) for item in (response.get("results") or [])
            )
            if normalized_item is not None
        ]

    payload = {
        "symbol": normalized_symbol,
        "max_results": capped,
        "count": len(results),
        "headlines": results,
        "generated_at": now,
    }
    _search_cache[cache_key] = (now, payload)
    return payload


async def fetch_news_summary(symbol: str, *, lang: str = DEFAULT_LANG) -> dict[str, Any]:
    client = _create_client()
    normalized_symbol = symbol.upper()
    target_lang = normalize_lang(lang)
    query = (
        f"Summarize the latest market-moving news for {normalized_symbol}. "
        "Focus on price catalysts, earnings, guidance, regulation, or macro signals."
    )

    response = await run_sync_with_retries(
        client.search,
        query=query,
        topic="news",
        search_depth="advanced",
        max_results=5,
        include_answer=True,
    )

    answer = ""
    sources: list[str] = []

    if isinstance(response, dict):
        answer = str(response.get("answer", "")).strip()
        results = response.get("results", []) or []
        for item in results[:3]:
            title = str(item.get("title", "")).strip()
            content = str(item.get("content", "")).strip().replace("\n", " ")
            snippet = content[:180].strip()
            if title and snippet:
                sources.append(f"{title}: {snippet}")
            elif title:
                sources.append(title)

    sections = [section for section in [answer, "\n".join(sources)] if section]
    summary = "\n\n".join(sections).strip()

    if not summary:
        template = _NO_NEWS_FALLBACKS.get(target_lang, _NO_NEWS_FALLBACKS["en"])
        summary = template.format(symbol=normalized_symbol)
    else:
        summary = _localize_text(summary, target_lang, kind="news summary")

    return {
        "symbol": normalized_symbol,
        "summary": summary,
        "source": "Tavily",
    }
