"""Unit-тест PainCommentsService без БД (репозитории — заглушки)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.modules.analytics.services.pain_comments_service import PainCommentsService


class _StubUser:
    organization_id = uuid.uuid4()


class _StubPainRepo:
    def __init__(self, found: bool):
        self._found = found

    async def get_by_id(self, pain_id, user):
        return object() if self._found else None


class _StubCommentRepo:
    def __init__(self, total, rows):
        self._total = total
        self._rows = rows
        self.calls: dict = {}

    async def list_pain_comments_page(self, *, pain_id, link_id, subcategory, since=None, limit, offset):
        self.calls = dict(pain_id=pain_id, link_id=link_id, subcategory=subcategory, limit=limit, offset=offset)
        return self._total, self._rows


def _row(**kw):
    base = dict(
        id=uuid.uuid4(),
        text="комментарий",
        external_id="42",
        comment_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        publication_url="https://vk.com/wall-1_2",
        sentiment=None,
        message_type="complaint",
        is_official_response=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_raises_when_pain_not_found():
    svc = PainCommentsService(
        db=None,
        pain_repository=_StubPainRepo(found=False),
        comment_repository=_StubCommentRepo(0, []),
    )
    with pytest.raises(ValueError):
        await svc.list_comments(_StubUser(), str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_builds_page_skips_empty_text_and_computes_has_more():
    rows = [_row(text="первый"), _row(text="   "), _row(text="второй")]
    repo = _StubCommentRepo(total=10, rows=rows)
    svc = PainCommentsService(
        db=None,
        pain_repository=_StubPainRepo(found=True),
        comment_repository=repo,
    )

    page = await svc.list_comments(_StubUser(), str(uuid.uuid4()), limit=20, offset=0)

    # пустой по тексту row отброшен → 2 элемента
    assert len(page.items) == 2
    assert page.total == 10
    # url собирается с ?reply=<external_id>
    assert page.items[0].url == "https://vk.com/wall-1_2?reply=42"
    # offset(0) + 2 < total(10) → ещё есть
    assert page.has_more is True


@pytest.mark.asyncio
async def test_multiple_source_ids_are_forwarded_as_one_filter():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    repo = _StubCommentRepo(total=0, rows=[])
    svc = PainCommentsService(
        db=None,
        pain_repository=_StubPainRepo(found=True),
        comment_repository=repo,
    )

    await svc.list_comments(
        _StubUser(),
        str(uuid.uuid4()),
        public_social_link_id=",".join(map(str, link_ids)),
    )

    assert repo.calls["link_id"] == link_ids
