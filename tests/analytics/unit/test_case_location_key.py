from backend.modules.analytics.utils.case_extractor import case_location_key


def test_different_houses_get_different_keys():
    assert case_location_key("ул. Ленина 5") != case_location_key("ул. Ленина 12")


def test_same_address_variants_share_key():
    assert case_location_key("ул. Ленина, 5") == case_location_key("улица Ленина 5")


def test_house_letter_distinguished():
    assert case_location_key("ул. Мира 5а") != case_location_key("ул. Мира 5")


def test_street_only_unaffected():
    assert case_location_key("село Успенка") == case_location_key("с. Успенка")
    assert case_location_key("ул. Ленина") and "5" not in case_location_key("ул. Ленина")
