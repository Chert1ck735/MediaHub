"""Утилиты для работы со временем в аналитике (периоды, окна публикации)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


_DOW_LABEL: dict[int, str] = {
    0: "вс", 1: "пн", 2: "вт", 3: "ср", 4: "чт", 5: "пт", 6: "сб",
}


def period_to_since(period: str | None) -> datetime | None:
    """Конвертирует строковый период в datetime cutoff.

    ``None`` означает all-time без фильтра. Неизвестные значения тоже
    приводятся к ``None``.
    """

    if not period:
        return None
    p = period.lower().strip()
    now = datetime.now(timezone.utc)
    if p in {"today", "day", "1d", "сегодня", "день"}:
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if p in {"3days", "3d", "three_days", "три дня", "3 дня"}:
        return now - timedelta(days=3)
    if p in {"week", "7d", "неделя"}:
        return now - timedelta(days=7)
    if p in {"month", "30d", "месяц"}:
        return now - timedelta(days=30)
    if p in {"3months", "quarter", "90d", "квартал"}:
        return now - timedelta(days=90)
    if p in {"6months", "180d", "полгода"}:
        return now - timedelta(days=180)
    if p in {"year", "365d", "год"}:
        return now - timedelta(days=365)
    return None


def format_post_window(
    hour_rows: list[tuple[int, int]],
    dow_rows: list[tuple[int, int]],
) -> str | None:
    """Краткая подсказка по лучшему времени для поста-ответа.

    На вход — пары ``(hour, count)`` и ``(dow, count)`` из истории
    комментариев. На выход — строка вида «9–11 утра, вт/чт» для UI.
    """

    if not hour_rows or not dow_rows:
        return None
    top_hours = sorted(h for h, _ in hour_rows[:3])
    if not top_hours:
        return None
    h_lo, h_hi = top_hours[0], top_hours[-1] + 1
    daypart = "утра" if h_hi <= 12 else "дня" if h_hi <= 18 else "вечера"
    if h_lo == h_hi - 1:
        time_part = f"{h_lo}:00 {daypart}"
    else:
        time_part = f"{h_lo}–{h_hi} {daypart}"
    top_dows = [_DOW_LABEL.get(d, "?") for d, _ in dow_rows[:2]]
    day_part = "/".join(top_dows)
    return f"{time_part}, {day_part}"
