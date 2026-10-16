"""Unit-тест RebuildNeededService без БД (репозитории — заглушки)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.modules.analytics.services.rebuild_needed_service import RebuildNeededService


class _StubUser:
    organization_id = uuid.uuid4()


class _Snapshot:
    generated_at = datetime(2026, 6, 1, tzinfo=timezone.utc)


class _JustBuiltSnapshot:
    generated_at = datetime.now(timezone.utc)


class _StubSnapshotRepo:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    async def get_latest_vk(self, user):
        return self._snapshot


class _StubCommentRepo:
    def __init__(self, *, total=0, since=0, pending=0):
        self._total = total
        self._since = since
        self._pending = pending

    async def count_org_comments(self, user, *, since=None):
        return self._since if since is not None else self._total

    async def count_unanalyzed_comments(self, user):
        return self._pending


def _service(snapshot, comment_repo):
    return RebuildNeededService(
        db=None,
        snapshot_repository=_StubSnapshotRepo(snapshot),
        comment_repository=comment_repo,
    )


@pytest.mark.asyncio
async def test_no_snapshot_with_comments():
    svc = _service(None, _StubCommentRepo(total=5))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is True
    assert res.reason == "no_snapshot"
    assert res.new_comments == 5


@pytest.mark.asyncio
async def test_no_snapshot_no_data():
    svc = _service(None, _StubCommentRepo(total=0))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is False
    assert res.reason == "no_data"


@pytest.mark.asyncio
async def test_new_comments_since_snapshot():
    svc = _service(_Snapshot(), _StubCommentRepo(since=3, pending=0))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is True
    assert res.reason == "new_comments"
    assert res.new_comments == 3


@pytest.mark.asyncio
async def test_pending_classification_does_not_order_rebuild():
    """Очередь на классификацию разбирает воркер, а не пересборка.

    Пока в очереди что-то есть, а пересборка её не уменьшает, ответ «нужна»
    заставлял страницу пересобирать снапшот при каждом открытии.
    """

    svc = _service(_Snapshot(), _StubCommentRepo(since=0, pending=4))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is False
    assert res.reason == "pending_classification"
    assert res.pending_classification == 4


@pytest.mark.asyncio
async def test_fresh_snapshot_is_not_rebuilt_again():
    svc = _service(_JustBuiltSnapshot(), _StubCommentRepo(since=3, pending=0))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is False
    assert res.new_comments == 3


@pytest.mark.asyncio
async def test_up_to_date():
    svc = _service(_Snapshot(), _StubCommentRepo(since=0, pending=0))
    res = await svc.check(_StubUser())
    assert res.needs_rebuild is False
    assert res.reason == "up_to_date"
