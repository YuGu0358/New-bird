from __future__ import annotations

from app.services.social_providers.base import SocialSearchOptions


class XiaohongshuSocialProvider:
    """Placeholder provider for a future Xiaohongshu integration."""

    name = "xiaohongshu"

    def is_configured(self) -> bool:
        return False

    def status_note(self) -> str | None:
        return "当前仅保留占位。公开内容搜索接口尚未接入。"

    async def search(self, options: SocialSearchOptions) -> dict[str, Any]:
        raise RuntimeError(
            "Xiaohongshu public-content search is not implemented yet. "
            "Keep this provider as a placeholder until you choose a compliant data source."
        )
