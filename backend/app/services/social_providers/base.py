from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class SocialSearchOptions:
    """Normalized options shared by every social-platform provider."""

    query: str
    provider: str = "x"
    limit: int = 20
    lang: str | None = None
    exclude_reposts: bool = True
    exclude_replies: bool = True
    min_like_count: int = 0
    min_repost_count: int = 0
    exclude_terms: tuple[str, ...] = ()
    summarize: bool = False
    force_refresh: bool = False


class SocialProvider(Protocol):
    """Interface that each social search provider implements."""

    name: str

    def is_configured(self) -> bool:
        """Return whether the provider has the credentials it needs."""

    def status_note(self) -> str | None:
        """Return a short human-readable status note."""

    async def search(self, options: SocialSearchOptions) -> dict[str, Any]:
        """Search posts for a query and return a normalized payload."""
