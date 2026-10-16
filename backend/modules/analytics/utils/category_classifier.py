"""Нормализация категорий и подкатегорий VK-аналитики.

В отличие от ``case_extractor``, эти функции работают с уже извлечённой
парой ``category / subcategory`` (которую вернула LLM или rule-based слой)
и приводят её к каноническим именам из ``analytics.constants``.
"""
from __future__ import annotations

from backend.modules.analytics.constants import CATEGORY_ALIASES, SUBCATEGORY_ALIASES
from backend.modules.analytics.utils.case_extractor import normalize_case
from backend.modules.analytics.utils.sentiment_rules import (
    rule_category_from_topics,
    topics_for_text,
)
from backend.modules.analytics.utils.text_normalize import (
    match_alias,
    normalized_lookup_text,
    trim_text,
)


def match_solution(
    problem_title: str,
    solutions: list[dict[str, object]],
) -> dict[str, object] | None:
    """Находит решение, чьё ``problem`` пересекается с заголовком боли."""

    title = problem_title.lower()
    for item in solutions:
        problem = str(item.get("problem", "")).lower()
        if not problem:
            continue
        if problem in title or title in problem:
            return item
    return None


def looks_like_housing_tariff(source_text: str) -> bool:
    """Текст одновременно про тарифы/начисления и про ЖКХ."""

    low = normalized_lookup_text(source_text)
    has_tariff = any(token in low for token in ("тариф", "начислен", "платеж", "квартплат"))
    has_housing = any(token in low for token in ("жкх", "кап ремонт", "капремонт", "коммун", "управля", "ук"))
    return has_tariff and has_housing


def priority_category_from_source(source_text: str) -> str | None:
    """Резервная категоризация по тексту для случаев, когда LLM не определилась."""

    low = normalized_lookup_text(source_text)
    if not low:
        return None
    if looks_like_housing_tariff(low):
        return "ЖКХ и городская среда"
    priority_aliases = {
        "Безопасность и ЧС": CATEGORY_ALIASES["Безопасность и ЧС"],
        "Экономика, торговля и регулирование": ("магазин", "алкогол", "торгов", "продаж", "лиценз", "цена"),
    }
    return match_alias(low, priority_aliases)


def normalize_category(value: str, source_text: str) -> str:
    """Нормализует категорию с приоритетом ответа LLM над эвристиками.

    Порядок:
      1. Принять каноническую категорию LLM, если она матчится по alias.
      2. Иначе вывести из исходного текста через topic-rules.
      3. ``priority_category_from_source`` — только как последний fallback,
         не override (иначе одно слово «магазин» в дорожном комментарии
         форсит «Экономика/Торговля» и стирает ответ LLM).
    """

    matched = match_alias(value, CATEGORY_ALIASES)
    if matched:
        return matched

    rule_category = rule_category_from_topics(topics_for_text(source_text))
    if rule_category:
        return rule_category

    priority_category = priority_category_from_source(source_text)
    if priority_category:
        return priority_category

    return ""


def normalize_subcategory(
    category: str,
    subcategory: str,
    source_text: str,
) -> tuple[str, str]:
    """Нормализует подкатегорию, при необходимости перевешивая её на другую категорию."""

    clean_subcategory = trim_text(subcategory, 120)
    if not clean_subcategory:
        category_map = SUBCATEGORY_ALIASES.get(category, {})
        return category, match_alias(source_text, category_map) or ""

    category_map = SUBCATEGORY_ALIASES.get(category, {})
    matched = match_alias(clean_subcategory, category_map)
    if matched:
        return category, matched

    priority_category = priority_category_from_source(source_text)
    if priority_category == category:
        matched_from_text = match_alias(source_text, category_map)
        return category, matched_from_text or ""

    for candidate_category, items in SUBCATEGORY_ALIASES.items():
        matched = match_alias(clean_subcategory, items)
        if matched:
            return candidate_category, matched

    fallback_category = normalize_category(clean_subcategory or source_text, source_text)
    if fallback_category and fallback_category != category:
        return fallback_category, ""
    # Строка LLM не заматчилась ни в одну категорию: не выпускаем её в данные —
    # свободные формулировки («разное», «энергетика») плодят чипы вне таксономии.
    return category, match_alias(source_text, category_map) or ""


def normalize_hierarchy_values(
    *,
    category: str,
    subcategory: str,
    case_name: str,
    source_text: str,
) -> tuple[str, str, str]:
    """Полная нормализация триады «категория → подкатегория → кейс» одним вызовом."""

    normalized_category = normalize_category(category, source_text)
    normalized_category, normalized_subcategory = normalize_subcategory(
        normalized_category,
        subcategory,
        source_text,
    )
    normalized_case = normalize_case(
        case_name,
        category=normalized_category,
        subcategory=normalized_subcategory,
        source_text=source_text,
    )
    return normalized_category, normalized_subcategory, normalized_case
