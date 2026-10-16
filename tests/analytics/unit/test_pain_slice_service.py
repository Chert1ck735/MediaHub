"""Unit-тест PainSliceService без БД."""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from backend.modules.analytics.services.pain_slice_service import PainSliceService


class _StubCommentRepo:
    def __init__(self, *, publications=None, case_rows=None):
        self._publications = publications or {}
        self._case_rows = case_rows or []
        self.calls: dict = {}

    async def count_publications_by_pain(self, pain_ids, *, since=None, link_id=None):
        self.calls["count_publications"] = (pain_ids, since, link_id)
        return self._publications

    async def count_mentions_by_pain(self, pain_ids, *, since=None, link_id=None):
        return {}

    async def collect_comment_ids_by_pain(self, pain_ids, *, since=None, link_id=None):
        return {}

    async def list_case_counts_by_pain(self, pain_ids, *, since=None, link_id=None):
        self.calls["list_case_counts"] = (pain_ids, since, link_id)
        return self._case_rows


def test_severity_from_share_thresholds():
    f = PainSliceService.severity_from_share
    assert f(0, 100) == "low"
    assert f(10, 0) == "low"
    # severity = min(по доле, по абсолютному числу упоминаний)
    assert f(60, 200) == "critical"   # доля 0.30 и упоминаний 60 — оба critical
    assert f(25, 100) == "high"       # доля 0.25 (critical), но упоминаний 25 → high
    assert f(12, 100) == "medium"     # доля 0.12 (high), но упоминаний 12 → medium
    assert f(5, 100) == "low"         # доля 0.05 (medium), но упоминаний 5 → low
    assert f(2, 4) == "low"           # мелкий паблик: высокая доля, мало упоминаний


@pytest.mark.asyncio
async def test_count_publications_for_pain_extracts_key():
    pain_id = uuid.uuid4()
    repo = _StubCommentRepo(publications={str(pain_id): 3})
    svc = PainSliceService(db=None, comment_repository=repo)

    result = await svc.count_publications_for_pain(pain_id, link_id=uuid.uuid4())

    assert result == 3
    # делегирует в репозиторий со списком из одной боли
    assert repo.calls["count_publications"][0] == [pain_id]


@pytest.mark.asyncio
async def test_count_publications_for_pain_missing_returns_zero():
    svc = PainSliceService(db=None, comment_repository=_StubCommentRepo(publications={}))
    assert await svc.count_publications_for_pain(uuid.uuid4()) == 0


@pytest.mark.asyncio
async def test_collect_top_cases_can_return_full_detail_list(monkeypatch):
    pain_id = uuid.uuid4()
    rows = [
        SimpleNamespace(
            pain_id=pain_id,
            case_name=f"Lenina {index}",
            mentions_count=index,
            public_region="",
            public_name="",
            source_title="",
            sample_comment="",
            sample_address="",
            sample_address_hierarchy=None,
        )
        for index in range(1, 4)
    ]

    class _FakeMapService:
        def __init__(self, db):
            pass

        def cache_snapshot(self):
            return {}

        def cached_geocode_for_context(self, context, geo_cache):
            # Разные адреса — разные точки: склейка идёт по координатам,
            # и одна точка на всех схлопнула бы три кейса в один.
            index = int(context.case_name.rsplit(" ", 1)[-1])
            return {"lat": 56.0 + index / 100, "lon": 92.0 + index / 100}

    monkeypatch.setattr(
        "backend.modules.analytics.services.pain_slice_service.PainMapService",
        _FakeMapService,
    )
    svc = PainSliceService(db=None, comment_repository=_StubCommentRepo(case_rows=rows))

    limited = await svc.collect_top_cases([pain_id], limit_per_pain=2)
    full = await svc.collect_top_cases([pain_id], limit_per_pain=None)

    assert limited[str(pain_id)]["cases_count"] == 3
    assert len(limited[str(pain_id)]["top_cases"]) == 2
    assert full[str(pain_id)]["cases_count"] == 3
    assert len(full[str(pain_id)]["top_cases"]) == 3
