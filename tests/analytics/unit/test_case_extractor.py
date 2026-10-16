"""Характеристик-тесты: case_extractor (извлечение/нормализация адресных кейсов)."""
from __future__ import annotations

from backend.modules.analytics.utils.case_extractor import (
    case_dedupe_key,
    case_family_from_text,
    case_location_key,
    extract_case_from_text,
    extract_case_routes,
    infer_category,
    is_valid_case_title,
    looks_like_taxonomy_label,
    normalize_street_name,
)


def test_infer_category():
    assert infer_category("обвал на дороге, погибли люди") == "Безопасность и ЧС"
    assert infer_category("незаконный магазин с алкоголем") == "Экономика, торговля и регулирование"
    assert infer_category("нет отопления во дворе") == "ЖКХ и городская среда"
    assert infer_category("просто нейтральный текст") is None


def test_looks_like_taxonomy_label():
    assert looks_like_taxonomy_label("дороги и транспорт") is True
    assert looks_like_taxonomy_label("отопление") is True
    assert looks_like_taxonomy_label("") is True
    assert looks_like_taxonomy_label("ул. Ленина 5") is False


def test_extract_case_from_text():
    assert "Ленина" in extract_case_from_text("Проблема на улице Ленина уже месяц")
    assert extract_case_from_text("просто жалоба без локации") == ""
    assert extract_case_from_text("") == ""


def test_normalize_street_name():
    assert normalize_street_name("Ленинскую") == "Ленинская"
    assert normalize_street_name("Советской") == "Советская"
    assert normalize_street_name("Мира") == "Мира"


def test_extract_case_routes_lowercase_pairs():
    routes = extract_case_routes("маршрут канск-иланский отменили")
    assert "иланский:канск" in routes


def test_case_family_from_text():
    family = case_family_from_text("отписка, не отвечают на обращение")
    assert family is not None
    assert family[0] == "official_response"
    assert case_family_from_text("нейтральный текст про погоду") is None


def test_case_location_key_canonicalizes_variants():
    a = case_location_key("с. Успенка, Рыбинский район")
    b = case_location_key("село Успенка Рыбинского района, Красноярский край")
    assert a == b
    assert a != ""


def test_is_valid_case_title():
    assert is_valid_case_title("ул. Ленина 5") is True
    assert is_valid_case_title("край") is False           # слишком коротко
    assert is_valid_case_title("Красноярский край") is False  # слишком общий топоним
    assert is_valid_case_title("дороги и транспорт") is False  # taxonomy-имя


def test_case_dedupe_key_family_priority():
    key = case_dedupe_key("Тарифы ЖКХ", "начисления за квартплату задрали")
    assert key == "family:housing_tariffs"


def test_full_address_chain_survives_many_commas():
    """Полная иерархия «край, округ, село, улица, дом» — лучший адрес, а не перечисление."""
    assert is_valid_case_title(
        "Красноярский край, Рыбинский округ, село Рыбное, улица Ленина, дом 4"
    ) is True


def test_enumeration_of_streets_is_not_a_case():
    assert is_valid_case_title(
        "г. Иланский, ул. Фрунзе, пер. Алгасинский, пер. Пятилетки, Администрация"
    ) is False


def test_sentence_tail_is_not_a_street():
    """«...стим-ул. Однако, ...» — модель приняла конец предложения за адрес."""
    assert is_valid_case_title("ул. Однако") is False


def test_routes_rivers_and_vague_places_are_rejected():
    assert is_valid_case_title("маршрут 222-656 Ачинск -Слабцовка") is False
    assert is_valid_case_title("Енисей") is False
    assert is_valid_case_title("по всему городу") is False
    assert is_valid_case_title("Емельяновский район, наша улица") is False
    assert is_valid_case_title("поликлиники города") is False


def test_public_name_fragment_is_not_an_address():
    """«города Минусинска» — остаток обращения к паблику, а не адрес."""
    assert is_valid_case_title("города Минусинска") is False
    assert is_valid_case_title("Енисейского округа") is False
    # Именительный падеж — нормальный, пусть и широкий, кейс.
    assert is_valid_case_title("город Минусинск") is True

