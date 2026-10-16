"""Формулировка изменения к прошлому периоду."""
from backend.modules.report.services.pdf_builder import _delta


def test_growth_and_decline():
    assert _delta(135, 96) == "+41%"
    assert _delta(28, 41) == "−32%"


def test_no_change_is_zero_percent():
    # Никаких словесных оборотов — в отчёте только числа.
    assert _delta(50, 50) == "0%"


def test_no_previous_period_gives_nothing():
    # За всё время сравнивать не с чем.
    assert _delta(100, None) == ""


def test_growth_from_zero_shows_count():
    # Доля от нуля не определена, поэтому штуки.
    assert _delta(9, 0) == "+9"
    assert _delta(0, 0) == "0"
