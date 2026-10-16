"""In-memory rate limiter, sliding window per (key, route).

Зачем не slowapi/redis: один pip-пакет ради ~30 строк логики — overhead
больше пользы. Этот лимитер достаточен для single-process uvicorn
(текущий prod-сценарий: один воркер, один Ollama). Если когда-нибудь
будем масштабироваться горизонтально — переедем на Redis-based лимитер
(там уже state shared между процессами); пока этого нет.

Использование:
    from backend.app.rate_limit import RateLimiter

    llm_limit = RateLimiter(max_calls=10, window_seconds=60)

    @router.post("/generate")
    async def generate(
        current_user: User = Depends(get_current_user),
    ):
        await llm_limit.check_async(key=str(current_user.id), route="llm.generate")
        ...

Логика: per ключ хранятся timestamps последних запросов в deque.
При вызове .check_async() выбрасываются устаревшие (старше окна), считается
длина. Если >= max_calls — HTTPException(429).

Поток: thread-safe через asyncio.Lock (не threading.Lock, потому что
uvicorn под Python — асинхронный, не многопоточный).
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from fastapi import HTTPException, status


@dataclass
class RateLimiter:
    max_calls: int
    window_seconds: int
    _buckets: dict[str, deque[float]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def check_async(self, key: str, route: str = "") -> None:
        """Async-версия. Бросает HTTPException(429) если лимит превышен."""
        composite = f"{route}:{key}" if route else key
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self._lock:
            dq = self._buckets.get(composite)
            if dq is None:
                dq = deque()
                self._buckets[composite] = dq
            # Чистим старые
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.max_calls:
                retry_after = max(1, int(self.window_seconds - (now - dq[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded: {self.max_calls} requests per {self.window_seconds}s. Retry after {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
            dq.append(now)
