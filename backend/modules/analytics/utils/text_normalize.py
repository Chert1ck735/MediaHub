"""Базовые функции нормализации текста.

Используются другими утилитами и сервисами analytics для приведения
свободного текста к виду, удобному для сопоставления со словарями
категорий, тем и кейсов.
"""
from __future__ import annotations


def trim_text(value: str, limit: int = 240) -> str:
    """Сжимает пробелы и обрезает текст до указанной длины."""

    text = " ".join(value.split())
    return text[:limit].strip()


def normalized_lookup_text(value: str) -> str:
    """Приводит строку к lower-case и заменяет «ё» на «е» для устойчивого matching."""

    return " ".join(value.lower().replace("ё", "е").split())


def match_alias(value: str, aliases_map: dict[str, tuple[str, ...]]) -> str | None:
    """Ищет первый канонический ключ из словаря синонимов, чьи варианты пересекаются со значением."""

    normalized = normalized_lookup_text(value)
    if not normalized:
        return None
    allow_reverse = len(normalized) >= 5  # короткий шум не матчим по обратному вхождению
    for canonical, aliases in aliases_map.items():
        # Канонический ключ тоже нормализуем: иначе «Управление и обратная
        # связь» не совпадает само с собой из-за регистра и уходит в «Связь»
        # по алиасу "связь".
        variants = tuple(normalized_lookup_text(item) for item in (canonical, *aliases))
        if any(
            alias in normalized or (allow_reverse and normalized in alias)
            for alias in variants
        ):
            return canonical
    return None


def append_unique(items: list[str], value: str, limit: int) -> None:
    """Добавляет нормализованное значение в список, если его там ещё нет и не превышен лимит."""

    normalized = value.strip()
    if not normalized or normalized in items or len(items) >= limit:
        return
    items.append(normalized)


def string_dict(value: object) -> dict[str, str]:
    """Преобразует произвольный dict-like объект в `dict[str, str]`, отбрасывая мусор."""

    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str) or raw is None:
            continue
        text = str(raw).strip()
        if text:
            normalized[key] = text
    return normalized
