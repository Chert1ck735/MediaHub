"""Unit-тест пост-обработки SnapshotSignalsService без БД."""
from __future__ import annotations

import uuid

import pytest

from backend.db.enums import SentimentEnum
from backend.modules.analytics.services.snapshot_signals_service import SnapshotSignalsService


class _StubUser:
    organization_id = uuid.uuid4()


class _StubSignalsRepo:
    async def count_total_comments(self, user, *, since, link_id, municipality_name=None):
        return 20

    async def count_classified_comments(self, user, *, since, link_id, municipality_name=None):
        return 14

    async def count_relevant_comments(self, snapshot_uuid, *, since, link_id, municipality_name=None):
        return 8

    async def count_relevant_by_message_types(
        self, user, *, message_types, since, link_id, municipality_name=None
    ):
        if "request" in message_types and "complaint" in message_types:
            return 8
        if "complaint" in message_types:
            return 5
        if message_types == ["request"]:
            return 3
        return 0

    async def count_appeals(self, user, *, since, link_id, municipality_name=None):
        return 8

    async def count_gratitude(self, user, *, since, link_id, municipality_name=None):
        return 2

    async def sentiment_rows(self, user, *, since, link_id, municipality_name=None):
        return [(SentimentEnum.negative, 4), (SentimentEnum.positive, 1)]

    async def message_type_rows(self, user, *, since, link_id, municipality_name=None):
        return [("complaint", 5), ("request", 3), ("unknown", 9)]

    async def category_rows(self, user, *, since, link_id, municipality_name=None):
        return [("ЖКХ", 10), ("Другое", 2), ("", 1)]

    async def category_sentiment_rows(self, user, *, since, link_id, municipality_name=None):
        return [("ЖКХ", SentimentEnum.negative, 7)]

    async def hour_rows(self, user, *, since, link_id, municipality_name=None):
        return [(9, 5), (10, 3), (11, 2)]

    async def dow_rows(self, user, *, since, link_id, municipality_name=None):
        return [(2, 4), (4, 3)]


@pytest.mark.asyncio
async def test_get_counts_post_processing():
    svc = SnapshotSignalsService(db=None, signals_repository=_StubSignalsRepo())

    result = await svc.get_counts(str(uuid.uuid4()), _StubUser())

    assert result["total_comments"] == 20
    assert result["classified_comments"] == 14
    assert result["relevant_comments"] == 8
    assert result["filtered"] == 12  # max(20-8, 0)
    assert result["complaints"] == 5
    assert result["requests"] == 3
    assert result["gratitude"] == 2
    assert result["appeals"] == 8

    # инвариант: обращения + благодарности + прочее = классифицированные
    assert result["other"] == 4
    assert result["appeals"] + result["gratitude"] + result["other"] == result["classified_comments"]

    assert result["sentiment_breakdown"]["negative"] == 4
    assert result["sentiment_breakdown"]["positive"] == 1
    assert result["message_type_breakdown"]["complaint"] == 5
    assert result["message_type_breakdown"]["request"] == 3

    # category_breakdown: сортировка по count убыв., первая — ЖКХ с негативом
    cats = result["category_breakdown"]
    assert cats[0]["category"] == "ЖКХ"
    assert cats[0]["count"] == 10
    assert cats[0]["negative_count"] == 7

    # unclassified = только пустая категория ("" → "Без категории"); "Другое" — обычная категория
    assert result["unclassified_count"] == 1

    assert result["relevance_breakdown"] == {"relevant": 8, "irrelevant": 12}

    window = result["recommended_post_window"]
    assert window.startswith("9")
    assert "утра" in window and "вт/чт" in window
