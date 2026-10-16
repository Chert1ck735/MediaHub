"""Unit-тест логики PainTrendsService (раскладка по неделям) без БД."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from backend.modules.analytics.services.pain_trends_service import PainTrendsService


class _StubUser:
    organization_id = uuid.uuid4()


class _StubPainRepository:
    """Возвращает заранее заданные строки (pain_id, comment_id, date)."""

    def __init__(self, rows):
        self._rows = rows
        self.calls: list = []
        self.link_filters: list = []

    async def list_pain_comment_mentions(self, user, *, since, link_id=None):
        self.calls.append(since)
        self.link_filters.append(link_id)
        return self._rows


@pytest.mark.asyncio
async def test_last_bucket_is_not_truncated():
    """Регрессия: хвост ряда не должен проседать на равномерных данных.

    Раньше границы якорились к НАЧАЛУ последнего дня, поэтому последний бакет
    вмещал одни сутки против семи у остальных — и график всегда «падал».
    """

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pain_id = uuid.uuid4()
    # Ровно два упоминания каждый день на протяжении четырёх недель.
    rows = [
        (pain_id, uuid.uuid4(), now - timedelta(days=day, hours=hour))
        for day in range(28)
        for hour in (3, 9)
    ]
    service = PainTrendsService(db=None, pain_repository=_StubPainRepository(rows))

    result = await service.list_trends(_StubUser(), since=now - timedelta(days=28))

    counts = result[0].counts
    assert result[0].bucket_days == 7
    assert counts == [14, 14, 14, 14]


@pytest.mark.asyncio
async def test_week_period_uses_daily_buckets():
    """Период «неделя» → элементарное деление в сутки."""

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pain_id = uuid.uuid4()
    rows = [
        (pain_id, uuid.uuid4(), now + timedelta(hours=2)),
        (pain_id, uuid.uuid4(), now + timedelta(hours=6)),
        (pain_id, uuid.uuid4(), now - timedelta(days=2) + timedelta(hours=1)),
    ]
    service = PainTrendsService(db=None, pain_repository=_StubPainRepository(rows))

    result = await service.list_trends(_StubUser(), since=now - timedelta(days=7))

    item = result[0]
    assert item.bucket_days == 1
    assert len(item.counts) == 7
    assert item.counts[-1] == 2   # последний день полноценный
    assert item.counts[-3] == 1
    assert sum(item.counts) == 3


@pytest.mark.asyncio
async def test_quarter_period_uses_weekly_buckets():
    """Период «3 месяца» → элементарное деление в неделю."""

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pain_id = uuid.uuid4()
    rows = [(pain_id, uuid.uuid4(), now - timedelta(days=offset)) for offset in (0, 3, 30)]
    service = PainTrendsService(db=None, pain_repository=_StubPainRepository(rows))

    result = await service.list_trends(_StubUser(), since=now - timedelta(days=90))

    item = result[0]
    assert item.bucket_days == 7
    assert len(item.counts) == 13
    assert item.counts[-1] == 2  # текущая неделя: сегодня и три дня назад
    assert sum(item.counts) == 3


@pytest.mark.asyncio
async def test_naive_datetime_and_none_handled():
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    since = now - timedelta(days=14)
    pain_id = uuid.uuid4()
    rows = [
        (pain_id, uuid.uuid4(), now.replace(tzinfo=None)),  # naive → учитывается
        (pain_id, uuid.uuid4(), None),       # None date → пропускаем
        (None, uuid.uuid4(), now),           # None pain_id → пропускаем
    ]
    service = PainTrendsService(db=None, pain_repository=_StubPainRepository(rows))

    result = await service.list_trends(_StubUser(), since=since)

    assert len(result) == 1
    assert sum(result[0].counts) == 1


@pytest.mark.asyncio
async def test_full_history_fetched_and_buckets_clamped():
    # Окно якорится к последней дате данных, история тянется целиком (since=None),
    # а число точек зажимается потолком _MAX_BUCKETS — иначе спарклайн превращается в шум.
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    pain_id = uuid.uuid4()
    rows = [
        (pain_id, uuid.uuid4(), now),
        (pain_id, uuid.uuid4(), now - timedelta(weeks=399)),  # огромный размах
    ]
    repo = _StubPainRepository(rows)
    service = PainTrendsService(db=None, pain_repository=repo)

    result = await service.list_trends(_StubUser(), since=None)

    assert repo.calls == [None]  # тянем всю историю, окно якорим в сервисе
    assert len(result) == 1
    assert len(result[0].counts) == 26
    assert result[0].bucket_days > 30  # размах огромный → бакет крупнее месяца


@pytest.mark.asyncio
async def test_empty_rows_return_empty():
    service = PainTrendsService(db=None, pain_repository=_StubPainRepository([]))
    assert await service.list_trends(_StubUser(), since=None) == []


@pytest.mark.asyncio
async def test_multiple_source_ids_are_queried_together():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    repo = _StubPainRepository([])
    service = PainTrendsService(db=None, pain_repository=repo)

    await service.list_trends(_StubUser(), since=None, link_id=link_ids)

    assert repo.link_filters == [link_ids]
