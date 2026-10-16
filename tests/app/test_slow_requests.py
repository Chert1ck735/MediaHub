"""Диагностика медленных ответов должна срабатывать, а не просто импортироваться."""
import asyncio
import logging
import re
import time
import types

import pytest

from backend.app import slow_requests


def _request(path: str = "/api/analytics/publics"):
    return types.SimpleNamespace(method="GET", url=types.SimpleNamespace(path=path))


@pytest.mark.asyncio
async def test_slow_response_is_logged(caplog):
    async def handler(_request):
        await asyncio.sleep(0)
        return "ok"

    # Порог опускаем, чтобы тест не спал секунду.
    original = slow_requests.SLOW_REQUEST_SECONDS
    slow_requests.SLOW_REQUEST_SECONDS = 0.0
    try:
        with caplog.at_level(logging.WARNING, logger=slow_requests.__name__):
            assert await slow_requests.log_slow_requests(_request(), handler) == "ok"
    finally:
        slow_requests.SLOW_REQUEST_SECONDS = original

    assert any("Медленный ответ" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_fast_response_is_not_logged(caplog):
    async def handler(_request):
        return "ok"

    with caplog.at_level(logging.WARNING, logger=slow_requests.__name__):
        await slow_requests.log_slow_requests(_request(), handler)

    assert not caplog.records


@pytest.mark.asyncio
async def test_blocked_loop_is_detected(monkeypatch, caplog):
    # Мерим часто, иначе тест ждал бы пять секунд.
    monkeypatch.setattr(slow_requests, "_LOOP_PROBE_INTERVAL", 0.05)
    monkeypatch.setattr(slow_requests, "_LOOP_LAG_WARN_SECONDS", 0.05)
    stop = asyncio.Event()

    with caplog.at_level(logging.WARNING, logger=slow_requests.__name__):
        task = asyncio.create_task(slow_requests.watch_event_loop_lag(stop))
        await asyncio.sleep(0.06)
        # Синхронная работа — ровно то, чем воркер занимает цикл.
        time.sleep(0.2)
        await asyncio.sleep(0.06)
        stop.set()
        await task

    # Проверяем записанное значение, а не текущее: следующий замер после
    # разблокировки уже показывает ноль, и «задержка сейчас» успевает сброситься.
    logged = [r.getMessage() for r in caplog.records if "Event loop занят" in r.getMessage()]
    assert logged, "занятость цикла не замечена"
    assert float(re.search(r"задержка ([\d.]+) с", logged[0]).group(1)) >= 0.05
