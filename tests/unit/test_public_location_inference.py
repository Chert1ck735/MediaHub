import pytest

from backend.modules.organization.municipalities import (
    canonical_municipality_name,
    infer_krasnoyarsk_municipality,
    mentions_krasnoyarsk_krai,
)
from backend.modules.analytics.utils.municipality_filter import (
    canonicalize_municipality_filters,
    municipality_aliases,
    raw_municipality_params,
)


def test_infers_municipality_from_vk_public_name_and_description():
    assert (
        infer_krasnoyarsk_municipality(
            "Администрация Назаровского муниципального округа",
            "Официальное сообщество администрации Назаровского округа",
        )
        == "Назаровский округ"
    )


def test_infers_city_from_genitive_public_name():
    assert (
        infer_krasnoyarsk_municipality("Администрация города Красноярска")
        == "Красноярск"
    )


def test_region_name_alone_does_not_match_city():
    assert infer_krasnoyarsk_municipality("Правительство Красноярского края") is None
    assert mentions_krasnoyarsk_krai("Правительство Красноярского края") is True


def test_canonicalizes_allowed_municipality_names():
    assert canonical_municipality_name("город Железногорск") == "Железногорск (ЗАТО)"


def test_builds_municipality_filter_aliases_for_old_address_names():
    aliases = municipality_aliases("Назаровский округ")

    assert "назаровский" in aliases
    assert "назарово" in aliases

    params = raw_municipality_params("Назаровский округ")
    assert params["municipality_public_name"] == "^(назаровский)$"
    assert "назаровский" in str(params["municipality_pattern"])


def test_filter_accepts_several_municipalities():
    assert canonicalize_municipality_filters("Абанский округ,Канский округ") == (
        "Абанский округ",
        "Канский округ",
    )
    # Повторы схлопываются, пробелы вокруг запятой не мешают.
    assert canonicalize_municipality_filters(" Канский округ , Канский округ ") == (
        "Канский округ",
    )

    aliases = municipality_aliases("Абанский округ,Канский округ")
    assert "абанский" in aliases
    assert "канский" in aliases

    params = raw_municipality_params("Абанский округ,Канский округ")
    assert params["municipality_public_name"] == "^(абанский|канский)$"


def test_unknown_municipality_in_list_is_rejected():
    # Молча отбросить неизвестное имя нельзя: пользователь увидел бы данные
    # не той территории, чем просил.
    with pytest.raises(ValueError):
        canonicalize_municipality_filters("Абанский округ,Марсианский округ")
