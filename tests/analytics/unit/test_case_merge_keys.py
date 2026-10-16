"""Ключи склейки адресов.

Каноническое имя от геокодера не уникально: «Нагорная улица» есть и в
Солонцах, и в Мазульском. По одному имени эти улицы слипались в одну, а
правильная склейка двух написаний солонцовской улицы при этом ломалась.
Координаты и подписи взяты из выгрузки карты.
"""
from backend.modules.analytics.utils.case_merge import CaseKeys

МАЗУЛЬСКИЙ = {"lat": 56.198916, "lon": 90.365748,
              "provider_name": "Нагорная улица", "locality": "городской посёлок Мазульский"}
СОЛОНЦЫ = {"lat": 56.05873, "lon": 92.852967,
           "provider_name": "Нагорная улица", "locality": "посёлок Солонцы"}
СОЛОНЦЫ_ИНАЧЕ = {"lat": 56.059464, "lon": 92.851368,
                 "provider_name": "Нагорная улица, Солонцы", "locality": "посёлок Солонцы"}


def test_same_street_name_in_two_villages_keeps_two_keys():
    keys = CaseKeys()

    first = keys.add("ул. Нагорная", МАЗУЛЬСКИЙ)[0]
    second = keys.add("ул. Нагорная", СОЛОНЦЫ)[0]

    assert first != second, "улицы разных сёл слиплись в одну"


def test_two_spellings_of_one_street_are_merged():
    keys = CaseKeys()

    keys.add("ул. Нагорная", МАЗУЛЬСКИЙ)
    street = keys.add("ул. Нагорная", СОЛОНЦЫ)[0]
    other = keys.add("Солонцы, Нагорная", СОЛОНЦЫ_ИНАЧЕ)[0]

    remap = keys.remap()
    # Какое из написаний станет главным — неважно, важно что строка одна.
    assert remap.get(street, street) == remap.get(other, other)


def test_street_and_house_stay_apart():
    keys = CaseKeys()

    street = keys.add("ул. Дубовицкого", {"lat": 56.057242, "lon": 92.852769,
                                          "provider_name": "улица Дубовицкого",
                                          "locality": "посёлок Солонцы"})[0]
    house = keys.add("Дубовицкого-1", {"lat": 56.056086, "lon": 92.853048,
                                       "provider_name": "улица Дубовицкого, 1",
                                       "locality": "посёлок Солонцы"})[0]

    assert street != house
    assert house not in keys.remap(), "дом свёлся к улице, номер потерялся"


def test_four_spellings_of_one_street_become_one():
    """Строки из карточки «Дороги»: одна улица приходила четырьмя написаниями."""

    keys = CaseKeys()
    variants = [
        ("ул. Нагорная", 56.05873, 92.852967, "Нагорная улица"),
        ("Нагорная Солонцы, посёлок Солонцы", 56.059464, 92.851368, "Нагорная улица, Солонцы"),
        ("Нагорная, посёлок Солонцы", 56.0590, 92.8520, "улица Нагорная"),
        ("Солонцы Нагорная, посёлок Солонцы", 56.0585, 92.8535, "Нагорная"),
    ]
    produced = [
        keys.add(title, {"lat": lat, "lon": lon, "provider_name": name,
                         "locality": "посёлок Солонцы"})[0]
        for title, lat, lon, name in variants
    ]
    far = keys.add("ул. Нагорная", {"lat": 56.198916, "lon": 90.365748,
                                    "provider_name": "Нагорная улица",
                                    "locality": "городской посёлок Мазульский"})[0]

    remap = keys.remap()
    final = {remap.get(key, key) for key in produced}

    assert len(final) == 1, "улица осталась несколькими строками"
    assert remap.get(far, far) not in final, "мазульская улица слилась с солонцовской"


def test_roads_without_a_name_are_not_merged():
    """«Дорога между домами …» после обрезки даёт одну и ту же подпись."""

    keys = CaseKeys()
    first = keys.add("Дорога Между Домами Киренского 116 и 118",
                     {"lat": 56.0100, "lon": 92.8600, "provider_name": "",
                      "locality": "Красноярск"})
    second = keys.add("Дорога От Дома Судостроительная 175 К Школе",
                      {"lat": 56.0120, "lon": 92.8650, "provider_name": "",
                       "locality": "Красноярск"})

    assert first is None or second is None or first[0] != second[0], (
        "разные дороги сложились в одну строку"
    )


def test_house_letter_is_kept():
    """«Чкалова 13 А» и «Чкалова 13 Б» — соседние дома, а не один."""

    keys = CaseKeys()
    geo = {"lat": 55.96, "lon": 92.38, "provider_name": "улица Чкалова",
           "locality": "Дивногорск"}

    first = keys.add("Чкалова 13 А, Дивногорск", dict(geo))[0]
    second = keys.add("Чкалова 13 Б, Дивногорск", dict(geo))[0]
    spelled = keys.add("Чкалова, 13Б", dict(geo))[0]

    remap = keys.remap()
    same = lambda one, two: remap.get(one, one) == remap.get(two, two)  # noqa: E731

    assert not same(first, second), "разные дома сложились в один"
    assert same(second, spelled), "«13 Б» и «13Б» — один дом"


def test_label_prefers_a_readable_form():
    """Из написаний одного места основным берётся человеческое."""

    from backend.modules.analytics.utils.case_extractor import case_location_key
    from backend.modules.analytics.utils.case_merge import label_rank

    cases = [
        (("школа №2, Минусинск", "2 Школы, Минусинск"), "Минусинск", "школа №2, Минусинск"),
        (("Карбышева, 10А, Красноярск", "Красноярск, Карбышева 10а"), "Красноярск",
         "Карбышева, 10А, Красноярск"),
    ]
    for variants, locality, expected in cases:
        place = frozenset(case_location_key(locality).split())
        assert min(variants, key=lambda one: label_rank(one, place)) == expected


def test_label_is_not_chosen_by_length_alone():
    """Варианты из выгрузки за всё время: короче — не значит лучше."""

    from backend.modules.analytics.utils.case_extractor import case_location_key
    from backend.modules.analytics.utils.case_merge import label_rank

    cases = [
        # Пропущенный пробел делает строку короче на символ.
        (("Ярыгинская Набережная, Красноярск", "ЯрыгинскаяНабережная, Красноярск"),
         "Красноярск", "Ярыгинская Набережная, Красноярск"),
        (("2 Микрорайон, Ачинск", "2Микрорайон, Ачинск"),
         "Ачинск", "2 Микрорайон, Ачинск"),
        # «ул.» длиннее, но заодно вытягивает название в именительный падеж.
        (("ул. Нагорная, городской посёлок Мазульский",
          "Нагорную, городской посёлок Мазульский"),
         "Мазульский", "ул. Нагорная, городской посёлок Мазульский"),
    ]
    for variants, locality, expected in cases:
        place = frozenset(case_location_key(locality).split())
        assert min(variants, key=lambda one: label_rank(one, place)) == expected
