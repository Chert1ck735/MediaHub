from backend.modules.analytics.utils.sentiment_rules import rule_category_from_topics


def test_substantive_topic_beats_governance():
    assert rule_category_from_topics({"governance", "roads"}) == "Дороги и транспорт"
    assert rule_category_from_topics({"governance", "telecom"}) == "Связь и цифровая инфраструктура"
    assert rule_category_from_topics({"governance", "social"}) == "Социальная сфера"


def test_governance_alone_stays_governance():
    assert rule_category_from_topics({"governance"}) == "Управление и обратная связь"


def test_safety_has_top_priority():
    assert rule_category_from_topics({"safety", "roads"}) == "Безопасность и ЧС"
