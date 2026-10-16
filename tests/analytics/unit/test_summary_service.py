"""Unit-тест AnalyticsSummaryService без БД (репозитории/сигналы — заглушки)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.modules.analytics.schemas import (
    MessageTypeBreakdown,
    RelevanceBreakdown,
    SentimentBreakdown,
)
from backend.modules.analytics.services.summary_service import AnalyticsSummaryService


class _StubUser:
    organization_id = uuid.uuid4()


def _snapshot():
    return SimpleNamespace(
        id=uuid.uuid4(),
        generated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        global_summary="итог",
        source_name="vk_auto_comments",
    )


def _counts():
    return {
        "relevant_comments": 10,
        "complaints": 4,
        "requests": 3,
        "appeals": 7,
        "gratitude": 2,
        "other": 5,
        "filtered": 1,
        "unclassified_count": 0,
        "recommended_post_window": "9–12 утра, вт/чт",
        "sentiment_breakdown": SentimentBreakdown(),
        "message_type_breakdown": MessageTypeBreakdown(),
        "relevance_breakdown": RelevanceBreakdown(),
        "category_breakdown": [],
    }


class _StubSnapshotRepo:
    def __init__(self, snapshot):
        self._snapshot = snapshot
        self.count_pains_called = False
        self.count_filtered_called_with = None

    async def get_latest_vk(self, user):
        return self._snapshot

    async def list_pains(self, snapshot_id):
        return [SimpleNamespace(title="Дороги"), SimpleNamespace(title="ЖКХ")]

    async def count_pains(self, snapshot_id):
        self.count_pains_called = True
        return 99

    async def count_filtered_pains(self, snapshot_id, link_id, *, since=None):
        self.count_filtered_called_with = (link_id, since)
        return 7


class _StubPublicationRepo:
    async def list_vk_public_names(self, user):
        return ["Паблик 1"]


class _StubSignals:
    def __init__(self):
        self.calls = []
        self.counts = _counts()

    async def get_counts(self, snapshot_id, user, *, since=None, link_id=None):
        self.calls.append((since, link_id))
        return self.counts


class _StubCommentRepo:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def sla_stats(self, user, *, since=None, link_id=None):
        self.calls.append((since, link_id))
        return self.result


def _service(snapshot):
    repo = _StubSnapshotRepo(snapshot)
    svc = AnalyticsSummaryService(
        db=None,
        snapshot_repository=repo,
        publication_repository=_StubPublicationRepo(),
        signals_service=_StubSignals(),
    )
    return svc, repo


@pytest.mark.asyncio
async def test_raises_when_no_snapshot():
    svc, _ = _service(None)
    with pytest.raises(ValueError):
        await svc.get_summary(_StubUser())


@pytest.mark.asyncio
async def test_no_link_uses_count_pains():
    svc, repo = _service(_snapshot())
    res = await svc.get_summary(_StubUser(), period="all", public_social_link_id=None)
    assert repo.count_pains_called is True
    assert repo.count_filtered_called_with is None
    assert res.pain_count == 99
    assert res.top_pains == ["Дороги", "ЖКХ"]
    assert res.source_label == "Соцсети"


@pytest.mark.asyncio
async def test_with_link_uses_count_filtered_pains():
    link_id = uuid.uuid4()
    svc, repo = _service(_snapshot())
    res = await svc.get_summary(_StubUser(), period="month", public_social_link_id=str(link_id))
    assert repo.count_filtered_called_with is not None
    called_link, called_since = repo.count_filtered_called_with
    assert called_link == link_id
    assert called_since is not None  # period="month" → cutoff передан
    assert res.pain_count == 7


@pytest.mark.asyncio
async def test_multiple_links_use_one_combined_query_and_keep_categories_and_sla():
    link_ids = [uuid.uuid4(), uuid.uuid4()]
    svc, repo = _service(_snapshot())
    svc._signals_service.counts["category_breakdown"] = [
        {
            "category": "Дороги",
            "count": 6,
            "negative_count": 4,
            "neutral_count": 2,
            "positive_count": 0,
        }
    ]
    sla_repo = _StubCommentRepo({
        "appeals": 7,
        "answered": 5,
        "response_rate": 71.4,
        "median_hours": 12.0,
        "avg_hours": 15.5,
        "within_sla_rate": 80.0,
        "sla_hours": 48.0,
        "official_total": 5,
    })
    svc._comment_repository = sla_repo

    result = await svc.get_summary(
        _StubUser(),
        period="month",
        public_social_link_id=",".join(map(str, link_ids)),
    )

    assert svc._signals_service.calls[-1][1] == link_ids
    assert repo.count_filtered_called_with[0] == link_ids
    assert sla_repo.calls[-1][1] == link_ids
    assert result.category_breakdown[0].category == "Дороги"
    assert result.sla.median_hours == 12.0
    assert result.sla.avg_hours == 15.5
    assert result.sla.within_sla_rate == 80.0
