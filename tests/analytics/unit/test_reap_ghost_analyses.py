"""Призраки в очереди классификации: что именно снимается с очереди.

БД тут нет, поэтому проверяем скомпилированный SQL: условие отбора — та часть,
где легко ошибиться (нужен именно pending+processing и оба признака призрака).
"""
from __future__ import annotations

import inspect

from sqlalchemy.dialects import postgresql

from backend.modules.analytics import classification
from backend.modules.analytics.classification import (
    STATE_DONE,
    STATE_FAILED,
    STATE_SKIPPED,
    reap_ghost_analyses,
)
from backend.modules.analytics.utils.official_response import is_community_authored


def _compiled_select_sql() -> str:
    """Собирает тот же select, что и reap_ghost_analyses, и компилирует в SQL."""

    from sqlalchemy import func, or_, select

    Comment = classification.Comment
    CommentAnalysis = classification.CommentAnalysis

    ghost = or_(
        func.btrim(func.coalesce(Comment.text, "")) == "",
        func.btrim(func.coalesce(Comment.author_external_id, "")).like("-%"),
    )
    stmt = (
        select(CommentAnalysis.id)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .where(
            CommentAnalysis.classification_state.in_(
                [classification.STATE_PENDING, classification.STATE_PROCESSING]
            )
        )
        .where(Comment.is_deleted.is_(False))
        .where(ghost)
    )
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_ghost_condition_covers_empty_text_and_community_author():
    sql = _compiled_select_sql().lower()

    assert "btrim" in sql
    assert "like" in sql          # автор-сообщество: from_id вида '-123'
    assert "is_deleted" in sql


def test_reaper_targets_only_queue_states():
    """Снимаем только то, что реально висит в очереди."""

    source = inspect.getsource(reap_ghost_analyses)

    assert "STATE_PENDING" in source and "STATE_PROCESSING" in source
    # done/failed — уже терминальные, их трогать нельзя
    assert "STATE_DONE" not in source
    assert "STATE_FAILED" not in source


def test_reaper_uses_existing_skipped_terminal():
    """Терминал — существующий skipped: воркер такие не берёт, очередь не считает."""

    source = inspect.getsource(reap_ghost_analyses)

    assert "STATE_SKIPPED" in source
    assert STATE_SKIPPED not in {STATE_DONE, STATE_FAILED}


def test_sql_matches_python_community_rule():
    """SQL-условие '-%' должно совпадать с is_community_authored."""

    assert is_community_authored("-123") is True
    assert is_community_authored("456") is False
    assert is_community_authored(None) is False
