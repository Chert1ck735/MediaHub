"""Обращение определено в одном месте: SLA, категории и /summary считают одинаково."""
from __future__ import annotations

import inspect

from backend.modules.analytics.constants import (
    APPEAL_MESSAGE_TYPES,
    COMPLAINT_MESSAGE_TYPES,
    GRATITUDE_MESSAGE_TYPES,
)
from backend.modules.analytics.repositories import comment_repository, signals_repository


def test_appeal_types_are_complaints_plus_requests():
    assert set(APPEAL_MESSAGE_TYPES) == set(COMPLAINT_MESSAGE_TYPES) | {"request"}
    assert not set(APPEAL_MESSAGE_TYPES) & set(GRATITUDE_MESSAGE_TYPES)


def test_category_rows_use_appeal_definition():
    source = inspect.getsource(signals_repository.SignalsRepository.category_rows)
    assert "APPEAL_MESSAGE_TYPES" in source
    assert "RelevanceEnum.relevant" in source


def test_sla_uses_appeal_definition():
    source = inspect.getsource(comment_repository.CommentRepository.sla_stats)
    # тип обращения приходит параметром из констант, а не списком в SQL
    assert ":appeal_types" in source
    assert "'complaint'" not in source
    # тот же скоуп, что у сигналов: сеть, завершённый разбор, без ответов сообщества
    assert ":networks" in source
    assert "classification_state = 'done'" in source
    assert "author_external_id NOT LIKE '-%'" in source
    # разметка правилами тоже считается обращением
    assert "classification_source" not in source
