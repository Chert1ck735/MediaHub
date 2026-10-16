"""Unit-тест перенесённых частей PainDetailService без БД."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.db.enums import SentimentEnum
from backend.modules.analytics.services.pain_detail_service import PainDetailService


class _StubCommentRepo:
    def __init__(self, *, signal_rows=None, recent_rows=None):
        self._signal_rows = signal_rows or []
        self._recent_rows = recent_rows or []

    async def signal_counts_rows_for_pain(self, pain_id, link_id=None, *, since=None):
        return self._signal_rows

    async def recent_comments_for_pain(self, pain_id, link_id, *, limit=5):
        return self._recent_rows


def _service(repo):
    return PainDetailService(db=None, comment_repository=repo)


@pytest.mark.asyncio
async def test_signal_counts_aggregation():
    rows = [
        (SentimentEnum.negative, "complaint", 3),
        (SentimentEnum.positive, "gratitude", 2),
        (None, "offtopic", 1),                 # sentiment None → в тональность не идёт
        (SentimentEnum.neutral, "unknown", 5),  # неизвестный message_type → игнор
    ]
    svc = _service(_StubCommentRepo(signal_rows=rows))

    result = await svc._get_signal_counts_for_pain(uuid.uuid4(), uuid.uuid4())

    assert result["sentiment_counts"] == {"positive": 2, "neutral": 5, "negative": 3}
    assert result["message_type_counts"]["complaint"] == 3
    assert result["message_type_counts"]["gratitude"] == 2
    assert result["message_type_counts"]["offtopic"] == 1
    assert result["message_type_counts"]["request"] == 0


@pytest.mark.asyncio
async def test_fallback_comment_examples_builds_and_skips_empty():
    recent = [
        SimpleNamespace(
            id=uuid.uuid4(),
            text="реальный комментарий",
            external_id="7",
            publication_url="https://vk.com/wall-1_2",
            message_type="complaint",
            sentiment=SentimentEnum.negative,
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            text="   ",  # пустой → пропускаем
            external_id="8",
            publication_url="https://vk.com/wall-1_3",
            message_type=None,
            sentiment=None,
        ),
    ]
    svc = _service(_StubCommentRepo(recent_rows=recent))

    result = await svc._fallback_comment_examples(uuid.uuid4(), uuid.uuid4())

    assert len(result) == 1
    assert result[0]["text"] == "реальный комментарий"
    assert result[0]["url"] == "https://vk.com/wall-1_2?reply=7"
    assert result[0]["sentiment"] == "negative"
