"""Характеристик-тесты: category_classifier (нормализация категорий/подкатегорий)."""
from __future__ import annotations

from backend.modules.analytics.constants import CATEGORY_ALIASES
from backend.modules.analytics.utils.category_classifier import (
    looks_like_housing_tariff,
    match_solution,
    normalize_category,
    normalize_subcategory,
    priority_category_from_source,
)


def test_match_solution():
    solutions = [{"problem": "ямы на дорогах", "fix": "ремонт"}]
    assert match_solution("Большие ямы на дорогах района", solutions) == solutions[0]
    assert match_solution("совсем другая тема", solutions) is None


def test_looks_like_housing_tariff():
    assert looks_like_housing_tariff("завышенный тариф ЖКХ в квитанции") is True
    assert looks_like_housing_tariff("просто яма на дороге") is False


def test_priority_category_from_source():
    assert priority_category_from_source("завышенные начисления по квартплате ЖКХ") == "ЖКХ и городская среда"
    assert priority_category_from_source("обвал и авария, есть погибшие") == "Безопасность и ЧС"
    assert priority_category_from_source("") is None


def test_normalize_category_prefers_llm_alias():
    # значение LLM матчится по alias → берём каноническое имя
    assert normalize_category("дороги", "любой текст") == "Дороги и транспорт"
    # LLM не дала валидную категорию → выводим из текста (topic-rules)
    assert normalize_category("", "нет отопления в доме") == "ЖКХ и городская среда"
    # ничего не матчится → пустая строка
    assert normalize_category("", "нейтральный текст без тем") == ""


def test_normalize_subcategory_matches_within_category():
    category, subcategory = normalize_subcategory(
        "Дороги и транспорт",
        "качество дорог",
        "вся дорога в ямах",
    )
    assert category == "Дороги и транспорт"
    assert subcategory == "качество дорог"


def test_every_canonical_category_matches_itself():
    """Категория должна распознаваться по собственному имени, а не по алиасу.

    Регресс: «Управление и обратная связь» матчилось по алиасу "связь" и
    уезжало в «Связь и цифровую инфраструктуру» вместе со своими
    подкатегориями, которых в таксономии Связи нет.
    """
    for category in CATEGORY_ALIASES:
        assert normalize_category(category, "") == category


def test_management_category_survives_normalization():
    category, subcategory = normalize_subcategory(
        normalize_category("Управление и обратная связь", "не отвечают на обращение"),
        "ответы ведомств",
        "не отвечают на обращение уже месяц",
    )

    assert category == "Управление и обратная связь"
    assert subcategory == "ответы ведомств"
