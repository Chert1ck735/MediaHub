"""Парсинг дат VK/Дзен-выгрузок.

Период фильтра здесь НЕ разбирается: единственный парсер живёт в
``analytics.utils.time_helpers.period_to_since``. Своя копия тут уже
приводила к тому, что «за 3 месяца» в Статистике означало «за всё время»:
копия не знала значений ``3months``/``6months``, которые шлёт фронт.
"""
from __future__ import annotations

from datetime import datetime

from backend.modules.analytics.utils.time_helpers import period_to_since

__all__ = ["parse_vk_datetime", "period_cutoff", "period_to_since"]


def parse_vk_datetime(value) -> datetime | None:
    """Разбирает дату VK-поста из произвольного формата."""

    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def period_cutoff(period: str) -> datetime | None:
    """Старое имя ``period_to_since``, оставлено для существующих вызовов."""

    return period_to_since(period)
