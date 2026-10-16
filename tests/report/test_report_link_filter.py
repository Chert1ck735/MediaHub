"""Фильтр площадок в отчёте должен разбираться, а не уходить строкой.

Строку «id,id» фильтр считает последовательностью и разбирает по буквам:
в запрос уходило сравнение колонки с отдельными символами, и отчёт с любой
выбранной площадкой падал с 500.
"""
import uuid

from backend.modules.analytics.utils.public_link_filter import (
    normalize_public_social_link_ids,
)
from backend.modules.report.services.pdf_report_service import _link_filter


def test_two_sources_become_two_ids():
    first, second = uuid.uuid4(), uuid.uuid4()

    parsed = _link_filter(f"{first},{second}")

    assert normalize_public_social_link_ids(parsed) == [first, second]


def test_single_source_becomes_one_id():
    only = uuid.uuid4()

    assert normalize_public_social_link_ids(_link_filter(str(only))) == [only]


def test_empty_means_no_filter():
    assert _link_filter(None) is None
    assert _link_filter("") is None


def test_raw_string_would_have_been_split_by_characters():
    # Показываем причину падения: без разбора строка расходится на символы.
    raw = str(uuid.uuid4())
    assert len(normalize_public_social_link_ids(raw)) > 1
    assert len(normalize_public_social_link_ids(_link_filter(raw))) == 1
