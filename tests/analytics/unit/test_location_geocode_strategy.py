import pytest

from backend.modules.analytics.utils.geocode import GeoPoint
from backend.modules.analytics.utils.location_geocode_strategy import (
    LocationContext,
    accept_geocode_result,
    build_geocode_queries,
    locality_from_public,
)


def test_queries_do_not_force_krasnoyarsk_for_unscoped_city():
    _region, queries = build_geocode_queries(LocationContext(case_name="город Ейск"))

    assert queries[0] == "город Ейск"
    assert all("Красноярский край" not in query for query in queries)


def test_street_without_city_uses_regional_capital():
    region, queries = build_geocode_queries(
        LocationContext(
            case_name="Волгоградская, 39",
            public_region="Красноярский край",
        )
    )

    assert region == "Красноярский край"
    assert "Красноярский край, Красноярск, Волгоградская, 39" in queries


def test_comment_municipality_context_precedes_capital_fallback():
    _region, queries = build_geocode_queries(
        LocationContext(
            case_name="ул. Парковая 43",
            public_region="Красноярский край",
            comment_text="[club|Администрация Назаровского муниципального округа], вы сами ходите по ул. Парковая 43?",
        )
    )

    assert queries.index("Красноярский край, Назаровского муниципального округа, ул. Парковая 43") < queries.index(
        "Красноярский край, Красноярск, ул. Парковая 43"
    )


def test_llm_address_hierarchy_has_first_priority():
    _region, queries = build_geocode_queries(
        LocationContext(
            case_name="ул. Парковая 43",
            public_region="Красноярский край",
            address="Назаровский муниципальный округ, ул. Парковая, 43",
            address_hierarchy={
                "municipality": "Назаровский муниципальный округ",
                "street": "ул. Парковая",
                "house": "43",
            },
        )
    )

    assert queries[0] == "Красноярский край, Назаровский муниципальный округ, ул. Парковая, 43"


def test_rejects_plain_source_region_capital_point():
    point = GeoPoint(
        lat=56.0,
        lon=92.8,
        region="Красноярский край",
        municipality="городской округ Красноярск",
        locality="Красноярск",
        district="городской округ Красноярск",
        source="yandex",
        precision="other",
        provider_kind="locality",
        provider_name="Красноярск",
        provider_text="Россия, Красноярский край, Красноярск",
    )

    assert not accept_geocode_result(
        LocationContext(case_name="Красноярск", public_region="Красноярский край"),
        "Красноярский край, Красноярск",
        "Красноярский край",
        point,
    )


def test_accepts_locality_centroid_with_matching_name():
    """Центроид населённого пункта годится, когда имя совпало."""

    point = GeoPoint(
        lat=55.957726,
        lon=92.380148,
        region="Красноярский край",
        municipality="городской округ Дивногорск",
        locality="Дивногорск",
        district="городской округ Дивногорск",
        source="yandex",
        precision="other",
        provider_kind="locality",
        provider_name="Дивногорск",
        provider_text="Россия, Красноярский край, Дивногорск",
    )

    assert accept_geocode_result(
        LocationContext(case_name="город Дивногорск"),
        "город Дивногорск",
        "",
        point,
    )


def test_rejects_point_outside_the_region():
    """Регион паблика может быть не заполнен — тогда берём край установки.

    Без этого «Трасса 42, 2» находилась в Туркестане и попадала на карту.
    """

    point = GeoPoint(
        lat=43.297,
        lon=68.252,
        region="Туркестанская область",
        municipality="",
        locality="Туркестан",
        district="",
        source="yandex",
        precision="other",
        provider_name="Туркестан",
        provider_text="Казахстан, Туркестанская область, Туркестан",
    )

    assert not accept_geocode_result(
        LocationContext(case_name="Трасса 42, 2"),
        "Трасса 42, 2",
        "",
        point,
    )


def _point(municipality: str, locality: str) -> GeoPoint:
    return GeoPoint(
        lat=56.0, lon=93.0, region="Красноярский край",
        municipality=municipality, locality=locality, district="",
        source="yandex", precision="street", provider_name="улица Мира",
        provider_description=locality, provider_kind="street",
        provider_text=f"Красноярский край, {locality}, улица Мира",
    )


def test_public_city_precedes_capital_for_street_case():
    _region, queries = build_geocode_queries(
        LocationContext(
            case_name="улица Мира",
            public_region="Красноярский край",
            public_name="Железногорск | Новости города",
        )
    )

    assert queries[0] == "Красноярский край, Железногорск, улица Мира"


def test_rejects_foreign_municipality_for_generic_street_query():
    ctx = LocationContext(
        case_name="улица Мира",
        public_region="Красноярский край",
        public_name="Железногорск | Новости города",
        comment_text="Когда починят освещение на улице Мира?",
    )

    norilsk = _point("городской округ Норильск", "Норильск")
    assert not accept_geocode_result(ctx, "Красноярский край, улица Мира", "Красноярский край", norilsk)

    zhel = _point("ЗАТО Железногорск", "Железногорск")
    assert accept_geocode_result(
        ctx, "Красноярский край, Железногорск, улица Мира", "Красноярский край", zhel
    )


def test_city_named_in_comment_overrides_public_city():
    ctx = LocationContext(
        case_name="улица Мира",
        public_region="Красноярский край",
        public_name="Железногорск | Новости города",
        comment_text="Я вчера был в Норильске — на улице Мира сплошные ямы.",
    )

    norilsk = _point("городской округ Норильск", "Норильск")
    assert accept_geocode_result(ctx, "Красноярский край, улица Мира", "Красноярский край", norilsk)


@pytest.mark.parametrize(
    ("public_name", "expected"),
    [
        ("Администрация города Дивногорска", "Дивногорск"),
        ("Администрация Ачинского муниципального округа", "Ачинск"),
        ("Администрация Минусинского округа", "Минусинск"),
        ("Администрация Енисейского округа", "Енисейск"),
        ("Администрация Шушенского округа", "Шушенское"),
        ("Администрация города Норильска", "Норильск"),
        ("Администрация Емельяновского  округа", "Емельяново"),
        ('МКУ "ЕДДС" Назаровского муниципального округа', "Назарово"),
        ("Администрация ЗАТО г. Железногорск", "Железногорск"),
        ("Администрация ЗАТО г. Зеленогорск", "Зеленогорск"),
        ("Город Дудинка", "Дудинка"),
    ],
)
def test_locality_from_public_reads_inflected_names(public_name: str, expected: str):
    assert locality_from_public(public_name) == expected


def test_compound_locality_wins_over_its_part():
    assert locality_from_public("Администрация Северо-Енисейского округа") == "Северо-Енисейский"


def test_regional_capital_is_not_a_public_locality():
    assert locality_from_public("Город Красноярск") == ""
    assert locality_from_public("Управление дорог / Красноярск") == ""


def test_rejects_other_city_point_for_inflected_public_name():
    ctx = LocationContext(
        case_name="улица Мира",
        public_region="Красноярский край",
        public_name="Администрация города Дивногорска",
        comment_text="Когда починят освещение на улице Мира?",
    )

    assert not accept_geocode_result(
        ctx,
        "Красноярский край, улица Мира",
        "Красноярский край",
        _point("городской округ Норильск", "Норильск"),
    )


def test_city_in_query_does_not_disable_foreign_city_guard():
    """Геокодер игнорирует «Ачинского округа» и отвечает Железногорском — не верим."""
    ctx = LocationContext(
        case_name="ул. Маяковского",
        public_region="Красноярский край",
        public_name="Администрация Ачинского муниципального округа",
        comment_text="Вот еще бы Маяковского почистили, по плану было на 9 января",
    )

    assert not accept_geocode_result(
        ctx,
        "Красноярский край, Ачинского муниципального округа, ул. Маяковского",
        "Красноярский край",
        _point("городской округ Железногорск", "Железногорск"),
    )


def test_city_guard_covers_cases_that_do_not_look_like_streets():
    """«парк на 1 м-не» из ачинского паблика не должен попадать в Красноярск."""
    ctx = LocationContext(
        case_name="парк на 1 м-не",
        public_region="Красноярский край",
        public_name="Администрация Ачинского муниципального округа",
        comment_text="как в парке на 1 м-не детская площадка, одно название",
    )

    assert not accept_geocode_result(
        ctx,
        "Красноярский край, парк на 1 м-не",
        "Красноярский край",
        _point("городской округ Красноярск", "Красноярск"),
    )


def test_admin_words_do_not_count_as_locality_mention():
    """Слово «города» в обращении к паблику не оправдывает точку в чужом городе."""
    ctx = LocationContext(
        case_name="ул. Б. Полевого, ул. Школьная",
        public_region="Красноярский край",
        public_name="Администрация города Дивногорска",
        comment_text="[club100423544|Администрация города Дивногорска], столбы поменяли",
    )

    assert not accept_geocode_result(
        ctx,
        "Красноярский край, ул. Б. Полевого, ул. Школьная",
        "Красноярский край",
        _point("городской округ ЗАТО Железногорск", "Железногорск"),
    )

