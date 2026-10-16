"""Unit-тест логики PainEventsService без БД (репозитории — заглушки)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.modules.analytics.services.pain_events_service import PainEventsService


class _StubUser:
    organization_id = uuid.uuid4()


class _StubPainRepo:
    def __init__(self, found: bool):
        self._found = found

    async def get_by_id(self, pain_id, user):
        return object() if self._found else None


class _StubEventRepo:
    def __init__(self, events, posts):
        self._events = events
        self._posts = posts

    async def list_events_for_pain(self, pain_id, user):
        return self._events

    async def list_posts_for_events(self, event_ids, user):
        return self._posts


@pytest.mark.asyncio
async def test_raises_when_pain_not_found():
    service = PainEventsService(
        db=None,
        pain_repository=_StubPainRepo(found=False),
        event_repository=_StubEventRepo([], []),
    )
    with pytest.raises(ValueError):
        await service.list_events(_StubUser(), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_groups_posts_under_events_and_builds_dto():
    event_id = uuid.uuid4()
    event_date = datetime(2026, 6, 1, tzinfo=timezone.utc)
    events = [(event_id, "Событие А", event_date, "Красноярск", "описание", "addresses")]
    posts = [
        (uuid.uuid4(), "Пост 1", event_id, datetime(2026, 6, 2, tzinfo=timezone.utc), "draft"),
        (uuid.uuid4(), None, event_id, None, "published"),
    ]
    service = PainEventsService(
        db=None,
        pain_repository=_StubPainRepo(found=True),
        event_repository=_StubEventRepo(events, posts),
    )

    result = await service.list_events(_StubUser(), str(uuid.uuid4()))

    assert len(result) == 1
    link = result[0]
    assert link.event_id == str(event_id)
    assert link.event_date == event_date.isoformat()
    assert len(link.posts) == 2
    # пост без названия получает заглушку
    titles = {p.title for p in link.posts}
    assert "(без названия)" in titles
