"""Согласие провайдеров как мера доверия к точке.

Разметка 26.08 на 530 местах: место, найденное одним провайдером, верно в 34%
случаев, двумя — в 82%, тремя — в 98%. Тесты фиксируют механику подсчёта.
"""
from __future__ import annotations

from backend.modules.analytics.utils.geocode import (
    GeoPoint,
    _split_leading_region,
    agreement,
)


def _point(lat: float, lon: float, source: str) -> GeoPoint:
    return GeoPoint(
        lat=lat, lon=lon, region="Красноярский край", municipality="Дивногорск",
        locality="Дивногорск", district="", source=source, precision="street",
        provider_name="улица Мира", provider_description="", provider_kind="street",
        provider_text="Красноярский край, Дивногорск, улица Мира",
    )


def test_agreement_counts_providers_pointing_at_one_place():
    candidates = [
        ("yandex", _point(55.9573, 92.3711, "yandex")),
        ("dadata_suggest_scoped", _point(55.9575, 92.3714, "dadata_suggest_scoped")),
    ]

    point, agreed = agreement(candidates)

    assert sorted(agreed) == ["dadata_suggest_scoped", "yandex"]
    assert point is not None and point.source == "yandex"


def test_distant_answers_do_not_agree():
    candidates = [
        ("yandex", _point(55.9573, 92.3711, "yandex")),
        ("dadata_suggest_scoped", _point(56.0104, 92.8523, "dadata_suggest_scoped")),
    ]

    _point_found, agreed = agreement(candidates)

    assert len(agreed) == 1


def test_agreement_is_empty_without_candidates():
    assert agreement([]) == (None, [])


def test_region_type_word_is_stripped_for_dadata():
    """DaData фильтрует по «Красноярский»; с «Красноярский край» подсказок нет."""
    assert _split_leading_region("Красноярский край, Дивногорск, ул. Мира") == (
        "Красноярский",
        "Дивногорск, ул. Мира",
    )
    assert _split_leading_region("Тверская область, Ржев") == ("Тверская", "Ржев")


def test_query_without_region_is_left_alone():
    assert _split_leading_region("Дивногорск, ул. Мира") == ("", "Дивногорск, ул. Мира")
