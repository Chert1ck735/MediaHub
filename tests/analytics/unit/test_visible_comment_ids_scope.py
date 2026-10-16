"""Период должен сужать выборку видимых комментариев, а не обнулять её.

Метод раньше отвечал пустым словарём, если не выбраны площадка или округ.
Из-за этого фильтрация контекста по периоду выкидывала из отчёта все примеры
комментариев и подпроблемы разом.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from backend.modules.analytics.repositories.comment_repository import CommentRepository


class _Db:
    def __init__(self):
        self.executed = False

    async def execute(self, _stmt):
        self.executed = True
        result = MagicMock()
        result.all.return_value = []
        return result


@pytest.mark.asyncio
async def test_period_alone_still_queries():
    db = _Db()
    repo = CommentRepository(db)

    await repo.collect_comment_ids_by_pain([uuid.uuid4()], since=object())

    assert db.executed, "при фильтре по периоду выборка обязана выполняться"


@pytest.mark.asyncio
async def test_no_filters_short_circuits():
    db = _Db()
    repo = CommentRepository(db)

    assert await repo.collect_comment_ids_by_pain([uuid.uuid4()]) == {}
    assert not db.executed, "без фильтров сужать нечего — лишний запрос не нужен"
