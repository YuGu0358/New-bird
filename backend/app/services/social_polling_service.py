from __future__ import annotations

import logging

from app.database import AsyncSessionLocal
from app.services import social_signal_service

logger = logging.getLogger(__name__)


def poll_interval_seconds() -> int:
    return social_signal_service.DEFAULT_SOCIAL_POLL_INTERVAL_MINUTES * 60


async def evaluate_once(*, execute: bool = False, force_refresh: bool = False) -> dict[str, object]:
    async with AsyncSessionLocal() as session:
        return await social_signal_service.run_social_monitor(
            session,
            include_watchlist=True,
            include_positions=True,
            include_candidates=True,
            execute=execute,
            force_refresh=force_refresh,
        )
