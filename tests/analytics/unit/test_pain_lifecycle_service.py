"""Unit-тест PainLifecycleService без БД (репозитории — заглушки)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.db.enums import PainStatusEnum
from backend.modules.analytics.services.pain_lifecycle_service import PainLifecycleService


class _StubEventRepo:
    def __init__(self, *, events_count=0, last_post_at=None, posts=None):
        self._events_count = events_count
        self._last_post_at = last_post_at
        self._posts = posts or []

    async def count_events_for_pain(self, pain_id):
        return self._events_count

    async def latest_post_at_for_pain(self, pain_id):
        return self._last_post_at

    async def list_posts_for_pain(self, pain_id):
        return self._posts


class _StubCommentRepo:
    """Возвращает счётчики по порядку вызовов (before, after, recent, ...)."""

    def __init__(self, counts):
        self._counts = list(counts)
        self._i = 0

    async def count_pain_comments_between(self, pain_id, *, start=None, end=None):
        value = self._counts[self._i]
        self._i += 1
        return value


def _svc(event_repo, comment_repo):
    return PainLifecycleService(db=None, comment_repository=comment_repo, event_repository=event_repo)


_AWARE = datetime(2026, 6, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_status_active_when_no_events():
    svc = _svc(_StubEventRepo(events_count=0), _StubCommentRepo([]))
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.active


@pytest.mark.asyncio
async def test_status_active_when_no_post():
    svc = _svc(_StubEventRepo(events_count=1, last_post_at=None), _StubCommentRepo([]))
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.active


@pytest.mark.asyncio
async def test_status_resolved_when_silent_after_post():
    # before=0, after=0, recent=0 → resolved
    svc = _svc(
        _StubEventRepo(events_count=1, last_post_at=_AWARE),
        _StubCommentRepo([0, 0, 0]),
    )
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.resolved


@pytest.mark.asyncio
async def test_status_reopened_when_recent_spike():
    # before=0, recent=6 (>5) → in_progress (боль вернулась)
    svc = _svc(
        _StubEventRepo(events_count=1, last_post_at=_AWARE),
        _StubCommentRepo([0, 0, 6]),
    )
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.in_progress


@pytest.mark.asyncio
async def test_status_resolved_when_big_drop():
    # before=10, after=4 → drop 60% ≥50, recent=0 → resolved
    svc = _svc(
        _StubEventRepo(events_count=1, last_post_at=_AWARE),
        _StubCommentRepo([10, 4, 0]),
    )
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.resolved


@pytest.mark.asyncio
async def test_status_in_progress_when_small_drop():
    # before=10, after=8 → drop 20% <50 → in_progress
    svc = _svc(
        _StubEventRepo(events_count=1, last_post_at=_AWARE),
        _StubCommentRepo([10, 8, 0]),
    )
    assert await svc.compute_status(uuid.uuid4()) == PainStatusEnum.in_progress


class _BatchEventRepo:
    def __init__(self, events, last_posts):
        self._events = events
        self._last_posts = last_posts

    async def count_events_by_pains(self, pain_ids):
        return {p: self._events[p] for p in pain_ids if p in self._events}

    async def latest_post_at_by_pains(self, pain_ids):
        return {p: self._last_posts[p] for p in pain_ids if self._last_posts.get(p)}


class _BatchCommentRepo:
    def __init__(self, recent, windows):
        self._recent = recent
        self._windows = windows
        self._calls = {}

    async def count_comments_since_by_pains(self, pain_ids, *, start):
        return {p: self._recent.get(p, 0) for p in pain_ids}

    async def count_pain_comments_between(self, pain_id, *, start=None, end=None):
        i = self._calls.get(pain_id, 0)
        self._calls[pain_id] = i + 1
        return self._windows[pain_id][i]


@pytest.mark.asyncio
async def test_compute_statuses_batch_matches_per_pain_logic():
    p_active, p_resolved, p_inprog = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    events = {p_resolved: 1, p_inprog: 1}
    last_posts = {p_resolved: _AWARE, p_inprog: _AWARE}
    windows = {p_resolved: (10, 4), p_inprog: (10, 8)}
    svc = PainLifecycleService(
        db=None,
        comment_repository=_BatchCommentRepo({p_resolved: 0, p_inprog: 0}, windows),
        event_repository=_BatchEventRepo(events, last_posts),
    )
    statuses = await svc.compute_statuses([p_active, p_resolved, p_inprog])
    assert statuses[p_active] == PainStatusEnum.active
    assert statuses[p_resolved] == PainStatusEnum.resolved
    assert statuses[p_inprog] == PainStatusEnum.in_progress


@pytest.mark.asyncio
async def test_reaction_gap_calc():
    posts = [(uuid.uuid4(), "Пост", _AWARE, None)]
    # before=10, after=5 → gap 50.0
    svc = _svc(
        _StubEventRepo(posts=posts),
        _StubCommentRepo([10, 5]),
    )
    result = await svc.compute_reaction_gap(uuid.uuid4())
    assert result["measured_events"] == 1
    assert result["avg_gap_pct"] == 50.0
    assert result["events"][0]["gap_pct"] == 50.0
    assert result["events"][0]["before_count"] == 10


@pytest.mark.asyncio
async def test_reaction_gap_none_when_no_before():
    posts = [(uuid.uuid4(), "Пост", _AWARE, None)]
    # before=0 → gap_pct None, не входит в среднее
    svc = _svc(
        _StubEventRepo(posts=posts),
        _StubCommentRepo([0, 3]),
    )
    result = await svc.compute_reaction_gap(uuid.uuid4())
    assert result["measured_events"] == 0
    assert result["avg_gap_pct"] is None
    assert result["events"][0]["gap_pct"] is None
