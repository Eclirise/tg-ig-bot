from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")


async def async_retry(
    func: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 1.0,
    jitter: float = 0.5,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await func()
        except retry_exceptions as exc:
            last_error = exc
            if attempt >= attempts:
                break
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0, jitter)
            await asyncio.sleep(delay)
    if last_error is None:
        raise RuntimeError("重试逻辑未捕获到异常，但调用未返回结果。")
    raise last_error
