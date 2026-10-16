"""История публикаций грузится окном, а не целиком.

Раньше ручка отдавала все посты организации, упиралась в таймаут шлюза, и
выборку пришлось обрезать до последних записей — из-за этого история
начиналась с сентября. Теперь страница просит показываемый период.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from backend.modules.calendar.repositories.calendar_repository import CalendarRepository


class _CapturingDb:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        result = MagicMock()
        result.scalars.return_value.unique.return_value.all.return_value = []
        return result


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect())).replace("\n", " ")


@pytest.mark.asyncio
async def test_window_filters_by_the_date_shown_in_the_calendar():
    db = _CapturingDb()
    since = datetime(2026, 1, 1, tzinfo=timezone.utc)
    until = datetime(2026, 2, 1, tzinfo=timezone.utc)

    await CalendarRepository(db).list_posts_with_publications(
        uuid.uuid4(), date_from=since, date_to=until
    )

    sql = _sql(db.statements[0])
    # Отбираем по дате показа, а не по времени импорта поста.
    assert "coalesce(publications.published_at, publications.scheduled_at" in sql
    assert sql.count(">=") == 1 and sql.count("<=") == 1


@pytest.mark.asyncio
async def test_without_a_window_the_answer_is_still_bounded():
    db = _CapturingDb()

    await CalendarRepository(db).list_posts_with_publications(uuid.uuid4())

    sql = _sql(db.statements[0])
    assert "LIMIT" in sql, "без окна ответ должен быть ограничен"
    assert ">=" not in sql and "<=" not in sql


@pytest.mark.asyncio
async def test_one_query_per_request():
    """Список и раньше собирался одним запросом — окно это не меняет."""

    db = _CapturingDb()

    await CalendarRepository(db).list_posts_with_publications(
        uuid.uuid4(), date_from=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert len(db.statements) == 1
