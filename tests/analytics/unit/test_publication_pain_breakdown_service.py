"""Unit-тест PublicationPainBreakdownService без БД (репозиторий — заглушка)."""
from __future__ import annotations

import uuid

import pytest

from backend.modules.analytics.services.publication_pain_breakdown_service import (
    PublicationPainBreakdownService,
)


class _StubUser:
    organization_id = uuid.uuid4()


class _StubRepo:
    def __init__(self, *, resolved, rows):
        self._resolved = resolved
        self._rows = rows
        self.calls: dict = {}

    async def resolve_publication_id(self, user, *, publication_id=None, url=None):
        self.calls["resolve"] = (publication_id, url)
        return self._resolved

    async def list_pain_breakdown_for_publication(self, publication_id, user):
        self.calls["breakdown"] = publication_id
        return self._rows


@pytest.mark.asyncio
async def test_requires_id_or_url():
    service = PublicationPainBreakdownService(db=None, publication_repository=_StubRepo(resolved=None, rows=[]))
    with pytest.raises(ValueError):
        await service.get_breakdown(_StubUser())


@pytest.mark.asyncio
async def test_not_found_raises_lookup_error():
    service = PublicationPainBreakdownService(
        db=None,
        publication_repository=_StubRepo(resolved=None, rows=[]),
    )
    with pytest.raises(LookupError):
        await service.get_breakdown(_StubUser(), publication_id=str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_builds_buckets_from_rows():
    pub_id = uuid.uuid4()
    pain_id = uuid.uuid4()
    rows = [(pain_id, "ЖКХ", "ЖКХ и городская среда", 7)]
    repo = _StubRepo(resolved=pub_id, rows=rows)
    service = PublicationPainBreakdownService(db=None, publication_repository=repo)

    result = await service.get_breakdown(_StubUser(), url="https://vk.com/wall-1_2")

    assert len(result) == 1
    assert result[0].pain_id == str(pain_id)
    assert result[0].comments_count == 7
    assert repo.calls["breakdown"] == pub_id
