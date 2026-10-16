"""Безопасное приведение к int.

Используется при чтении сырых CSV-полей и dict'ов из БД: значения там
могут оказаться строками, ``None`` или вовсе мусором. Один раз сложили
тут — чтобы caller не дублировал try/except в каждом месте.
"""
from __future__ import annotations


def safe_int(value, default: int = 0) -> int:
    """Возвращает ``int(value)`` или ``default``, если значение не парсится."""

    try:
        return int(value)
    except (ValueError, TypeError):
        return default
