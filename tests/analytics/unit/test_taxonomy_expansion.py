from backend.modules.analytics.utils.category_classifier import normalize_hierarchy_values
from backend.modules.analytics.utils.sentiment_rules import (
    rule_category_from_topics,
    topics_for_text,
)


def _cat(text: str) -> str:
    return rule_category_from_topics(topics_for_text(text))


def test_fire_goes_to_safety():
    assert _cat("в лесу пожар, задымление, дышать нечем") == "Безопасность и ЧС"


def test_flood_goes_to_safety():
    assert _cat("каждую весну паводок подтопляет улицу") == "Безопасность и ЧС"


def test_gasification_goes_to_housing():
    assert _cat("когда проведут газификацию посёлка") == "ЖКХ и городская среда"


def test_stray_dogs_go_to_ecology():
    assert _cat("по улице бегают бродячие собаки, отлова нет") == "Экология и санитарное состояние"


def test_noise_goes_to_ecology():
    assert _cat("по ночам шум, спать невозможно") == "Экология и санитарное состояние"


def test_new_subcategory_is_resolved():
    cat, sub, _case = normalize_hierarchy_values(
        category="", subcategory="", case_name="", source_text="в лесу пожар, горит"
    )
    assert cat == "Безопасность и ЧС"
    assert sub == "пожары"
