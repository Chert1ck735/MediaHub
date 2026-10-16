"""Что попадает в список «Адреса», а что нет.

Строки взяты из выгрузки карты: жители дописывают к адресу пояснение, а
модель кладёт в поле адреса и названия территорий.
"""
import pytest

from backend.modules.analytics.utils.address_normalizer import (
    address_display_title,
    is_address_like,
    trim_address_tail,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ул. Нагорная В Солонцах У Складов Янта", "ул. Нагорная"),
        ("Ул. Бувайсара Сайтиева (от Молокова До Краснодарской)", "Ул. Бувайсара Сайтиева"),
        ("Дубовицкого/нагорная - Многострадальные, Солонцы", "Дубовицкого"),
        ("ул. Забобонова и Ул.лесопарковой", "ул. Забобонова"),
        ("Северное Шоссе До Перекрестка Пограничников, Металлургов, Мост777", "Северное Шоссе"),
        ("ул. Дубовицкого", "ул. Дубовицкого"),
        ("Ленинградская, 44", "Ленинградская, 44"),
    ],
)
def test_tail_is_trimmed(raw, expected):
    assert trim_address_tail(raw) == expected


@pytest.mark.parametrize(
    "raw, geo",
    [
        ("Город Дивногорск", {"locality": "Дивногорск"}),
        ("ЗАТО Г. Железногорск", {"locality": "Железногорск"}),
        ("Солонцы, посёлок Солонцы", {"locality": "Солонцы"}),
        ("Пгт. Березовка, городской посёлок Берёзовка", {"locality": "Берёзовка"}),
        ("Центр Города Красноярска", {"locality": "Красноярск"}),
        ("Шушенский Район", {"municipality": "Шушенский район"}),
    ],
)
def test_territory_is_not_an_address(raw, geo):
    assert is_address_like(raw, geo) is False


@pytest.mark.parametrize(
    "raw, geo",
    [
        ("ул. Дубовицкого", {"locality": "Солонцы"}),
        ("Дубовицкого, посёлок Солонцы", {"locality": "Солонцы"}),
        ("Ленинградская, 44", {"locality": "Красноярск"}),
        ("школа №76, Дивногорск", {"locality": "Дивногорск"}),
        ("Нефтяников, 7, село Рыбное", {"locality": "Рыбное"}),
        ("ул. Нагорная В Солонцах У Складов Янта", {"locality": "Солонцы"}),
    ],
)
def test_address_stays(raw, geo):
    assert is_address_like(raw, geo) is True


def test_bare_house_number_is_not_an_address():
    assert is_address_like("5", {"locality": "Красноярск"}) is False


@pytest.mark.parametrize(
    "raw",
    [
        "дорога между домами Киренского 116 и 118",
        "проезд между Шевченко 46 и Шевченко 52",
        "дорога от Чкалова 45 к мед техникуму",
    ],
)
def test_detail_is_kept_when_trimming_would_empty_the_name(raw):
    """Без пояснения от «дороги» остаётся только слово «дорога».

    Раньше обрезка съедала подробности, и десяток разных мест выглядел
    одинаковыми строками «Дорога, Красноярск».
    """

    assert trim_address_tail(raw) == raw.replace(",", ", ").replace("  ", " ")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("ул. Вавилова, г Красноярск", "ул. Вавилова, Красноярск"),
        ("1 Зарельсовая, 27, город Боготол", "1 Зарельсовая, 27, Боготол"),
        ("Гагарина, г Ачинск", "Гагарина, Ачинск"),
    ],
)
def test_city_is_written_one_way(raw, expected):
    assert address_display_title(raw, {"locality": expected.split(", ")[-1]}) == expected


def test_settlement_type_is_kept():
    """«Село» и «посёлок» уточняют место, в отличие от «г»."""

    assert address_display_title(
        "Ленина, 4, село Рыбное", {"locality": "Рыбное"}
    ).endswith("Село Рыбное")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("переулок Медицинский", "пер. Медицинский"),
        ("проспект Котельникова", "просп. Котельникова"),
        ("микрорайон Солнечный", "мкр. Солнечный"),
        ("микрорайон Южный", "мкр. Южный"),
        ("ул. Нагорная", "ул. Нагорная"),
    ],
)
def test_street_kind_is_not_replaced_by_street(raw, expected):
    """Переулок и микрорайон — не улицы, и в подписи должны такими остаться."""

    assert address_display_title(raw, {"locality": "Красноярск"}).startswith(expected)


@pytest.mark.parametrize(
    "raw, expected",
    [
        # Тип отрывается только когда за ним настоящее название.
        ("наб. 51, село Овсянка", "наб. 51"),
        ("Проезд Между Шевченко 46 и Шевченко 52", "Проезд Между"),
        # Регистр типа не должен прыгать между строками одного списка.
        ("Ул. Тамбовская", "ул. Тамбовская"),
        ("ул. Чкалова", "ул. Чкалова"),
    ],
)
def test_street_kind_is_not_torn_off_a_house_number(raw, expected):
    assert address_display_title(raw, {"locality": "Красноярск"}).startswith(expected)
