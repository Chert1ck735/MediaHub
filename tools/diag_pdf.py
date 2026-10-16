"""Диагностика PDF-отчёта: прямой прогон генерации с трейсбеком и таймингами.

Запуск из корня: python -m tools.diag_pdf
Гоняет генерацию по всем периодам мимо HTTP-слоя. Если падает здесь — причина
в данных/рендере (трейсбек покажет). Если здесь работает, а через кнопку
падает — причина в окружении HTTP-пути (пул БД под нагрузкой воркера,
таймауты прокси): смотреть лог «PDF timings» рядом с ошибкой.
"""
import asyncio
import os
import time
import traceback

from sqlalchemy import select

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.report.schema import ReportGenerateRequest
from backend.modules.report.services.pdf_report_service import ReportPdfService

PERIODS = ("week", "month", "3months", "6months", "year", "all")


async def main() -> None:
    async with async_session_maker() as db:
        user = (await db.execute(select(User).limit(1))).scalar_one()
        svc = ReportPdfService(db)
        for period in PERIODS:
            started = time.monotonic()
            try:
                result = await svc.generate(user, ReportGenerateRequest(platform="vk", period=period))
                size = os.path.getsize(result.path)
                print(f"{period:8} OK   {time.monotonic() - started:6.1f}s  {size:>8} байт  {result.path}")
                os.remove(result.path)
            except Exception:
                print(f"{period:8} УПАЛО за {time.monotonic() - started:.1f}s")
                traceback.print_exc()


asyncio.run(main())
