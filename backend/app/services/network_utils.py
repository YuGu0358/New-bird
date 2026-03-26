from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")

_TRANSIENT_ERROR_MARKERS = (
    "connection reset by peer",
    "connection aborted",
    "remote end closed connection",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "connection refused",
    "server disconnected",
)


def _iter_exception_messages(exc: BaseException | None) -> list[str]:
    if exc is None:
        return []

    messages: list[str] = []
    queue: list[BaseException] = [exc]
    seen: set[int] = set()

    while queue:
        current = queue.pop(0)
        current_id = id(current)
        if current_id in seen:
            continue
        seen.add(current_id)

        text = str(current).strip()
        if text:
            messages.append(text)

        if getattr(current, "__cause__", None) is not None:
            queue.append(current.__cause__)
        if getattr(current, "__context__", None) is not None:
            queue.append(current.__context__)

        for item in getattr(current, "args", ()):
            if isinstance(item, BaseException):
                queue.append(item)
            elif isinstance(item, str) and item.strip():
                messages.append(item.strip())

    return messages


def is_transient_network_error(exc: BaseException) -> bool:
    lowered_messages = [message.lower() for message in _iter_exception_messages(exc)]
    return any(marker in message for message in lowered_messages for marker in _TRANSIENT_ERROR_MARKERS)


def friendly_service_error_detail(exc: BaseException) -> str:
    if is_transient_network_error(exc):
        return "外部数据源连接被重置或暂时不可用，请稍后重试。"
    return str(exc)


async def run_sync_with_retries(
    func: Callable[..., T],
    *args: Any,
    attempts: int = 3,
    delay_seconds: float = 0.6,
    **kwargs: Any,
) -> T:
    last_error: BaseException | None = None

    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= attempts or not is_transient_network_error(exc):
                raise
            await asyncio.sleep(delay_seconds * attempt)

    raise RuntimeError("Unexpected retry state.") from last_error
