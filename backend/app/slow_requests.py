"""Диагностика медленных ответов и голодания event loop.

Регулярные 504 на ``/api/analytics/publics`` и ``/api/calendar`` могут быть
двух разных природ: тяжёлый запрос к базе или то, что фоновые воркеры
(классификация, автопарсер) живут в одном процессе с веб-сервером и занимают
цикл событий. По одному времени ответа эти случаи не различить, поэтому рядом
пишется задержка цикла: если она большая, дело не в базе.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Порог, с которого ответ считается медленным и попадает в лог.
SLOW_REQUEST_SECONDS = 1.0

# Как часто мерить задержку цикла и с какого значения жаловаться.
_LOOP_PROBE_INTERVAL = 5.0
_LOOP_LAG_WARN_SECONDS = 0.5

# Последняя измеренная задержка — попадает в строку про медленный запрос.
_loop_lag_seconds = 0.0

# Последние медленные ответы держим в памяти: до логов сервера доступа нет,
# а лента Sentry Logs включается на стороне трекера и может быть выключена.
_recent: deque = deque(maxlen=50)


def snapshot() -> dict:
    """Что показать в браузере: текущая задержка цикла и последние ответы."""

    return {
        "порог_секунд": SLOW_REQUEST_SECONDS,
        "задержка_цикла_сейчас": round(_loop_lag_seconds, 2),
        "медленные_ответы": list(_recent),
    }


async def watch_event_loop_lag(stop_event: asyncio.Event) -> None:
    """Спит фиксированное время и смотрит, насколько сон затянулся.

    Разница между заказанным и фактическим сном — это время, которое цикл был
    занят чем-то другим. Ровно та величина, из-за которой веб-запросы ждут.
    """

    global _loop_lag_seconds
    while not stop_event.is_set():
        started = time.perf_counter()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_LOOP_PROBE_INTERVAL)
            return
        except asyncio.TimeoutError:
            pass
        _loop_lag_seconds = max(0.0, time.perf_counter() - started - _LOOP_PROBE_INTERVAL)
        if _loop_lag_seconds >= _LOOP_LAG_WARN_SECONDS:
            logger.warning(
                "Event loop занят: задержка %.2f с. Веб-запросы в это время ждут.",
                _loop_lag_seconds,
            )


async def log_slow_requests(request, call_next):
    """Пишет в лог ответы дольше порога вместе с задержкой цикла."""

    started = time.perf_counter()
    try:
        return await call_next(request)
    finally:
        elapsed = time.perf_counter() - started
        if elapsed >= SLOW_REQUEST_SECONDS:
            _recent.appendleft({
                "время": datetime.now(timezone.utc).strftime("%d.%m %H:%M:%S"),
                "путь": f"{request.method} {request.url.path}",
                "секунд": round(elapsed, 1),
                "задержка_цикла": round(_loop_lag_seconds, 2),
            })
            logger.warning(
                "Медленный ответ: %s %s — %.1f с (задержка цикла %.2f с)",
                request.method,
                request.url.path,
                elapsed,
                _loop_lag_seconds,
            )
