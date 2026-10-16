"""Форматирование окна активности аудитории.

На входе — гистограммы часов и дней недели от ``audience_repository``.
На выходе — короткая фраза для рекомендации редактору: «9–12 утра, вт/чт».
Если данных нет — возвращаем ``None``, чтобы caller не показывал пустую
подсказку.
"""
from __future__ import annotations

# Postgres extract('dow', ...) возвращает 0=вс, 1=пн, ..., 6=сб.
_DOW_LABEL = {0: "вс", 1: "пн", 2: "вт", 3: "ср", 4: "чт", 5: "пт", 6: "сб"}


def format_audience_window(
    hour_rows: list[tuple[int, int]],
    dow_rows: list[tuple[int, int]],
) -> str | None:
    """«9–12 утра, вт/чт» из топа часов и дней."""

    if not hour_rows or not dow_rows:
        return None
    top_hours = sorted(h for h, _ in hour_rows[:3])
    if not top_hours:
        return None
    h_lo, h_hi = top_hours[0], top_hours[-1] + 1
    daypart = "утра" if h_hi <= 12 else "дня" if h_hi <= 18 else "вечера"
    time_part = f"{h_lo}:00 {daypart}" if h_lo == h_hi - 1 else f"{h_lo}–{h_hi} {daypart}"
    top_dows = [_DOW_LABEL.get(d, "?") for d, _ in dow_rows[:2]]
    return f"{time_part}, {'/'.join(top_dows)}"
