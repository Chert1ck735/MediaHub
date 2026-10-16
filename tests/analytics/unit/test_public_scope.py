from backend.modules.analytics.utils.public_scope import (
    MUNICIPAL_CATEGORIES,
    infer_applicable_categories,
)


def test_municipality_gets_all_categories():
    assert infer_applicable_categories("Администрация города Красноярска") is None
    assert infer_applicable_categories("VK паблик 12345") is None


def test_theatre_is_restricted_and_excludes_roads():
    cats = infer_applicable_categories("Драматический театр имени Пушкина")
    assert cats is not None
    assert "Дороги и транспорт" not in cats
    assert "ЖКХ и городская среда" not in cats
    assert "Социальная сфера" in cats
    assert "Управление и обратная связь" in cats


def test_school_excludes_utilities():
    cats = infer_applicable_categories("Школа №10")
    assert cats is not None
    assert "ЖКХ и городская среда" not in cats
    assert "Социальная сфера" in cats


def test_inferred_categories_are_subset_of_municipal():
    cats = infer_applicable_categories("Городская поликлиника №1")
    assert cats is not None
    assert set(cats).issubset(MUNICIPAL_CATEGORIES)


def test_empty_name():
    assert infer_applicable_categories("") is None
    assert infer_applicable_categories(None) is None
