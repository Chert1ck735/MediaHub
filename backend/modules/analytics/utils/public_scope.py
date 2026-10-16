"""Зона ответственности паблика: какие категории болей к нему применимы."""
from __future__ import annotations

from backend.modules.analytics.constants import VK_THEME_META

MUNICIPAL_CATEGORIES: set[str] = {meta["category"] for meta in VK_THEME_META.values()}

_GOVERNANCE = "Управление и обратная связь"
_SOCIAL = "Социальная сфера"
_ECONOMY = "Экономика, торговля и регулирование"
_SAFETY = "Безопасность и ЧС"

# Специализированные паблики: ключ в названии → суженный набор категорий.
# Управление и обратная связь применимо ко всем. Матчим по названию (тип паблика
# обычно в нём), не по описанию — описание муниципалитета шумит профильными словами.
_PROFILES: tuple[tuple[tuple[str, ...], frozenset[str]], ...] = (
    (("театр", "музе", "библиотек", "дом культуры", "филармони", "галере",
      "концерт", "выставк", "культур"),
     frozenset({_SOCIAL, _GOVERNANCE, _ECONOMY})),
    (("школа", "школы", "гимнази", "лице", "детсад", "садик", "университет",
      "институт", "колледж"),
     frozenset({_SOCIAL, _GOVERNANCE, _SAFETY})),
    (("больниц", "поликлиник", "госпитал", "диспансер", "медцентр", "фап"),
     frozenset({_SOCIAL, _GOVERNANCE, _SAFETY})),
    (("стадион", "спорткомплекс", "бассейн", "фитнес"),
     frozenset({_SOCIAL, _GOVERNANCE})),
)


def infer_applicable_categories(name: str | None) -> list[str] | None:
    """Угадывает зону паблика по названию.

    Возвращает суженный список категорий для распознанного профильного паблика;
    None — паблик не распознан, применимы все категории."""
    if not name:
        return None
    low = name.lower()
    for keywords, categories in _PROFILES:
        if any(kw in low for kw in keywords):
            return sorted(categories)
    return None
