"""Фоновый цикл автопарсера: раз в AUTOPARSE_CHECK_INTERVAL_SECONDS будит
проверку «созревших» ссылок и парсит новые комментарии."""

from __future__ import annotations

import asyncio
import logging

from backend.app.config import settings as app_settings
from backend.modules.autoparse.service import AutoParseService

logger = logging.getLogger(__name__)


async def autoparse_loop(
    db_factory,
    *,
    stop_event: asyncio.Event,
    settings=app_settings,
) -> None:
    """Крутится до stop_event: каждый тик прогоняет только «созревшие» ссылки.

    Тик короче периода (AUTOPARSE_INTERVAL_HOURS), чтобы новые ссылки
    подхватывались без суток ожидания; сам период фильтруется в SQL по
    last_autoparse_at, поэтому лишних парсов частые тики не создают.
    """

    if not settings.AUTOPARSE_ENABLED:
        logger.info("Autoparse worker disabled (AUTOPARSE_ENABLED=false)")
        return

    service = AutoParseService(db_factory, settings=settings)
    check_interval = max(60, settings.AUTOPARSE_CHECK_INTERVAL_SECONDS)
    logger.info(
        "Autoparse worker started: interval=%dh lookback=%dd tick=%ds",
        settings.AUTOPARSE_INTERVAL_HOURS,
        settings.AUTOPARSE_LOOKBACK_DAYS,
        check_interval,
    )

    while not stop_event.is_set():
        try:
            await service.run_once(only_due=True)
        except Exception:
            logger.exception("Autoparse pass crashed")

        # Спим до следующего тика, но просыпаемся сразу при остановке.
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=check_interval)
        except asyncio.TimeoutError:
            pass
