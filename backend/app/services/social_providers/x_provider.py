from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app import runtime_settings
from app.services.social_providers.base import SocialSearchOptions

_X_API_BASE_URL = "https://api.x.com/2"


def build_x_query(
    query: str,
    *,
    lang: str | None = None,
    exclude_reposts: bool = True,
    exclude_replies: bool = True,
) -> str:
    """Append the common X operators needed by this project."""

    normalized = str(query or "").strip()
    if not normalized:
        raise ValueError("query is required for X search.")

    if lang and "lang:" not in normalized:
        normalized = f"{normalized} lang:{lang.lower()}"

    if exclude_reposts and "-is:retweet" not in normalized:
        normalized = f"{normalized} -is:retweet"

    if exclude_replies and "-is:reply" not in normalized:
        normalized = f"{normalized} -is:reply"

    return normalized.strip()


class XSocialProvider:
    """Recent-search provider backed by the official X API."""

    name = "x"

    def is_configured(self) -> bool:
        return bool(runtime_settings.get_setting("X_BEARER_TOKEN", ""))

    def status_note(self) -> str | None:
        if self.is_configured():
            return "已配置 Bearer Token，可搜索最近 7 天公开帖子。"
        return "缺少 X_BEARER_TOKEN，当前不能调用官方 Recent Search。"

    async def search(self, options: SocialSearchOptions) -> dict[str, Any]:
        token = runtime_settings.get_required_setting(
            "X_BEARER_TOKEN",
            "X_BEARER_TOKEN is missing. Configure it in the settings page or backend/.env first.",
        )

        normalized_query = build_x_query(
            options.query,
            lang=options.lang,
            exclude_reposts=options.exclude_reposts,
            exclude_replies=options.exclude_replies,
        )

        max_results = min(max(int(options.limit), 10), 100)
        headers = {"Authorization": f"Bearer {token}"}
        search_params = {
            "query": normalized_query,
            "max_results": max_results,
            "tweet.fields": "created_at,lang,author_id,public_metrics",
            "user.fields": "username,name,verified,public_metrics",
            "expansions": "author_id",
        }
        count_params = {
            "query": normalized_query,
            "granularity": "day",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{_X_API_BASE_URL}/tweets/search/recent",
                headers=headers,
                params=search_params,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = response.text.strip() or str(exc)
                raise RuntimeError(f"X recent search failed: {detail}") from exc

            payload = response.json()

            count_payload: dict[str, Any] = {}
            try:
                count_response = await client.get(
                    f"{_X_API_BASE_URL}/tweets/counts/recent",
                    headers=headers,
                    params=count_params,
                )
                count_response.raise_for_status()
                count_payload = count_response.json()
            except httpx.HTTPError:
                count_payload = {}

        users = {
            str(user.get("id")): user
            for user in (payload.get("includes", {}) or {}).get("users", []) or []
        }

        posts: list[dict[str, Any]] = []
        for item in payload.get("data", []) or []:
            post_id = str(item.get("id", "")).strip()
            author = users.get(str(item.get("author_id", "")), {})
            username = str(author.get("username", "")).strip()
            metrics = item.get("public_metrics", {}) or {}
            author_metrics = author.get("public_metrics", {}) or {}

            created_at = str(item.get("created_at", "")).strip()
            if created_at.endswith("Z"):
                created_at = created_at.replace("Z", "+00:00")

            posts.append(
                {
                    "provider": self.name,
                    "post_id": post_id,
                    "text": str(item.get("text", "")).strip(),
                    "created_at": created_at,
                    "url": (
                        f"https://x.com/{username}/status/{post_id}"
                        if username
                        else f"https://x.com/i/web/status/{post_id}"
                    ),
                    "lang": item.get("lang"),
                    "author": {
                        "id": str(author.get("id", "")).strip(),
                        "username": username or None,
                        "display_name": str(author.get("name", "")).strip() or None,
                        "verified": bool(author.get("verified", False)),
                        "followers_count": int(author_metrics.get("followers_count", 0) or 0),
                    },
                    "metrics": {
                        "like_count": int(metrics.get("like_count", 0) or 0),
                        "repost_count": int(metrics.get("retweet_count", 0) or 0),
                        "reply_count": int(metrics.get("reply_count", 0) or 0),
                        "quote_count": int(metrics.get("quote_count", 0) or 0),
                    },
                }
            )

        counts: list[dict[str, Any]] = []
        for bucket in count_payload.get("data", []) or []:
            start = str(bucket.get("start", "")).strip()
            end = str(bucket.get("end", "")).strip()
            if start.endswith("Z"):
                start = start.replace("Z", "+00:00")
            if end.endswith("Z"):
                end = end.replace("Z", "+00:00")
            counts.append(
                {
                    "start": start,
                    "end": end,
                    "post_count": int(bucket.get("tweet_count", 0) or 0),
                }
            )

        rate_limit_reset = response.headers.get("x-rate-limit-reset")

        return {
            "provider": self.name,
            "query": options.query,
            "normalized_query": normalized_query,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_results": sum(bucket["post_count"] for bucket in counts) or len(posts),
            "posts": posts,
            "counts": counts,
            "rate_limit_remaining": int(response.headers.get("x-rate-limit-remaining", "0") or 0),
            "rate_limit_reset": int(rate_limit_reset or 0) if rate_limit_reset else None,
        }
