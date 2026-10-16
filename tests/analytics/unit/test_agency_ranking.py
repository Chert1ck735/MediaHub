"""Агрегация рейтинга организаций: worst-first по доле ответов."""
from __future__ import annotations

from backend.modules.analytics.services.agency_ranking_service import aggregate_by_agency


def _inc(agency, status, mentions=1):
    return {"agency": agency, "status": status, "mentions": mentions}


def test_groups_and_counts_by_agency():
    rows = aggregate_by_agency([
        _inc("Минстрой", "in_work", 3),
        _inc("Минстрой", "overdue", 2),
        _inc("Минтранс", "new", 1),
    ])
    by = {r["agency"]: r for r in rows}
    assert by["Минстрой"]["incidents"] == 2
    assert by["Минстрой"]["mentions"] == 5
    assert by["Минстрой"]["answered"] == 1
    assert by["Минстрой"]["overdue"] == 1
    assert by["Минстрой"]["response_rate"] == 50.0


def test_skips_placeholder_agency():
    rows = aggregate_by_agency([_inc("—", "overdue"), _inc("Минстрой", "in_work")])
    assert [r["agency"] for r in rows] == ["Минстрой"]


def test_worst_responder_first():
    rows = aggregate_by_agency([
        _inc("Хороший", "in_work"),
        _inc("Плохой", "overdue"),
    ])
    assert rows[0]["agency"] == "Плохой"
