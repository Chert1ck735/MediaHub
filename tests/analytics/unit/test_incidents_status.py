"""Статус инцидента выводится из наличия ответа и возраста относительно SLA."""
from __future__ import annotations

from backend.modules.analytics.services.incidents_service import ROUTING, classify_status


def test_answered_is_in_work_regardless_of_age():
    assert classify_status(answered=1, age_hours=1000) == "in_work"
    assert classify_status(answered=3, age_hours=0) == "in_work"


def test_unanswered_over_sla_is_overdue():
    assert classify_status(answered=0, age_hours=49) == "overdue"


def test_unanswered_within_sla_is_new():
    assert classify_status(answered=0, age_hours=10) == "new"
    assert classify_status(answered=0, age_hours=48) == "new"


def test_unknown_age_is_new_not_overdue():
    assert classify_status(answered=0, age_hours=None) == "new"


def test_every_category_has_routing_default():
    for cat in ("жкх и городская среда", "дороги и транспорт", "неизвестная категория"):
        assert ROUTING.get(cat, "—")
