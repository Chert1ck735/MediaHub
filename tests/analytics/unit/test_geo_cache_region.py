"""Записи гео-кэша проверяются при чтении.

Кэш копился и по старым правилам: если у паблика не был указан регион,
принимался ответ откуда угодно. Так «Трасса 42, 2» осела с точкой в
Туркестане и продолжала попадать в отчёт даже после исправления правил.
"""
from unittest.mock import MagicMock

from backend.modules.analytics.services.pain_map_service import PainMapService
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    build_geocode_queries,
)


def _cache_for(title: str, entry: dict) -> dict:
    _, queries = build_geocode_queries(LocationContext(case_name=title))
    return {f"v2|{query}": entry for query in queries}


def _service() -> PainMapService:
    service = PainMapService.__new__(PainMapService)
    service._db = MagicMock()
    return service


def test_entry_outside_the_region_is_ignored():
    title = "Трасса 42, 2"
    cache = _cache_for(title, {
        "lat": 43.297, "lon": 68.252,
        "region": "Туркестанская область", "municipality": "", "locality": "Туркестан",
        "district": "", "source": "yandex", "provider_name": "Туркестан",
        "provider_text": "Казахстан, Туркестанская область, Туркестан",
    })

    got = _service().cached_geocode_for_context(LocationContext(case_name=title), cache)

    assert got is None, "точка из другой страны прошла из кэша"


def test_entry_inside_the_region_is_used():
    title = "улица Нагорная"
    entry = {
        "lat": 56.05873, "lon": 92.852967,
        "region": "Красноярский край", "municipality": "Емельяновский район",
        "locality": "Солонцы", "district": "Емельяновский район", "source": "yandex",
        "provider_name": "Нагорная улица",
        "provider_text": "Россия, Красноярский край, Солонцы, Нагорная улица",
    }

    got = _service().cached_geocode_for_context(
        LocationContext(case_name=title), _cache_for(title, entry)
    )

    assert got is not None and got["locality"] == "Солонцы"


def test_entry_from_a_neighbouring_city_is_still_used():
    """На чтении проверяем только край, а не весь набор правил приёмки.

    Полная приёмка отбраковывает точку из другого города, и на чтении улица
    уезжала в соседний населённый пункт: «ул. Гладкова, Красноярск»
    показывалась как «ул. Гладкова, посёлок городского типа Емельяново».
    """

    title = "улица Гладкова"
    entry = {
        "lat": 56.0184, "lon": 92.8672,
        "region": "Красноярский край", "municipality": "городской округ Красноярск",
        "locality": "Красноярск", "district": "Кировский район", "source": "yandex",
        "provider_name": "улица Гладкова",
        "provider_text": "Россия, Красноярский край, Красноярск, улица Гладкова",
    }

    got = _service().cached_geocode_for_context(
        LocationContext(case_name=title, public_name="Емельяново"), _cache_for(title, entry)
    )

    assert got is not None and got["locality"] == "Красноярск"
