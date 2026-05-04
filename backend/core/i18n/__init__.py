"""Backend-side language helpers used to localise LLM-generated text.

All endpoints that produce free-form text (news summaries, research
reports, AI Council verdicts, social-signal explanations, candidate-pool
reasons) consult `language_instruction(lang)` to inject a one-line system
directive that nudges the LLM to respond in the requested language.

The frontend ships the current i18n language as the `Accept-Language`
header (en | zh | de | fr). Anything else falls back to `en`.
"""
from __future__ import annotations

from typing import Iterable

SUPPORTED_LANGS: tuple[str, ...] = ("en", "zh", "de", "fr")
DEFAULT_LANG = "en"


# One-line nudges appended to LLM system prompts. Kept short — the LLM has
# already been given a heavy persona prompt; we just clamp output language.
_LANG_INSTRUCTIONS: dict[str, str] = {
    "en": "Respond in clear professional English.",
    "zh": "请用专业、简洁的简体中文回答。",
    "de": "Antworte auf klares, professionelles Deutsch.",
    "fr": "Réponds en français professionnel et clair.",
}

# Native-language labels used inside Tavily / OpenAI query templates so the
# search engine surfaces local-language sources where possible.
_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "zh": "Chinese (Simplified)",
    "de": "German",
    "fr": "French",
}


def normalize_lang(value: str | None, *, allowed: Iterable[str] = SUPPORTED_LANGS) -> str:
    """Coerce any incoming language string to one of the supported codes.

    Accepts BCP-47-ish strings (e.g. `zh-CN`, `en-US`) and reduces them to
    their primary subtag. Unknown languages collapse to DEFAULT_LANG.
    """
    if not value:
        return DEFAULT_LANG
    primary = str(value).strip().split(",")[0].split(";")[0].split("-")[0].lower()
    if primary in allowed:
        return primary
    return DEFAULT_LANG


def language_instruction(lang: str) -> str:
    """Return the one-line directive to append to a system prompt."""
    return _LANG_INSTRUCTIONS.get(normalize_lang(lang), _LANG_INSTRUCTIONS[DEFAULT_LANG])


def language_name(lang: str) -> str:
    """English name of a language (for use inside English-only prompt phrasing)."""
    return _LANG_NAMES.get(normalize_lang(lang), _LANG_NAMES[DEFAULT_LANG])
