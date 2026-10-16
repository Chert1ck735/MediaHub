"""Метрики площадок собираются пакетно.

Раньше на каждую ссылку уходило четыре запроса: при трёх сотнях площадок это
больше тысячи обращений к базе подряд, и список отвечал под сорок секунд.
Число запросов не должно зависеть от количества ссылок.
"""
import uuid
from unittest.mock import MagicMock

import pytest

from backend.modules.analytics.repositories.public_query_repository import (
    PublicQueryRepository,
)


class _CountingDb:
    def __init__(self):
        self.queries = 0

    async def execute(self, _statement):
        self.queries += 1
        result = MagicMock()
        result.all.return_value = []
        return result


def _links(count: int) -> list[dict]:
    return [{"id": str(uuid.uuid4())} for _ in range(count)]


@pytest.mark.asyncio
async def test_query_count_does_not_grow_with_links():
    few, many = _CountingDb(), _CountingDb()

    await PublicQueryRepository(few)._fill_metrics_for_links(_links(3))
    await PublicQueryRepository(many)._fill_metrics_for_links(_links(300))

    assert few.queries == many.queries, "число запросов зависит от количества площадок"
    assert few.queries <= 4


@pytest.mark.asyncio
async def test_no_links_means_no_queries():
    db = _CountingDb()

    await PublicQueryRepository(db)._fill_metrics_for_links([])

    assert db.queries == 0


@pytest.mark.asyncio
async def test_links_without_data_get_zeroes():
    db = _CountingDb()
    links = _links(2)

    await PublicQueryRepository(db)._fill_metrics_for_links(links)

    # База ничего не вернула — поля всё равно должны быть заполнены нулями,
    # иначе фронт получит ответ без ожидаемых ключей.
    for link in links:
        assert link["publications_count"] == 0
        assert link["total_views"] == 0
        assert link["total_comments"] == 0
        assert link["first_comment_at"] is None
