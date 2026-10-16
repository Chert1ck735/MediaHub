"""Импорт группы OK, когда статистика недоступна (токен не администратора)."""

import uuid

import pytest

from backend.modules.ok.links.link_parser import OkLinkParser
from backend.modules.ok.services.ingestion_service import OkIngestionService
from backend.modules.ok.utils.errors import OkApiError

GID = "53458237653184"


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)
        self.id = kw.get("id", uuid.uuid4())


class FakeApiClient:
    """API-клиент: статистика закрыта (456), остальное работает."""

    def __init__(self):
        self.public_feed_calls = []

    def get_group(self, group_ref):
        return {"uid": GID, "name": "Тестовая группа", "shortname": "testgrp", "members_count": 10}

    def fetch_all_stat_topics(self, gid, **kwargs):
        raise OkApiError("GROUP_RESTRICTION : errors.group.cannot_view_stats", code=456)

    def fetch_public_topic_ids(self, group_id, *, shortname=None, max_topics=None, on_progress=None):
        self.public_feed_calls.append({"group_id": group_id, "shortname": shortname, "max_topics": max_topics})
        return ["111", "222"]

    def get_mediatopics(self, topic_ids):
        return [
            {
                "id": tid,
                "created_ms": 1_700_000_000_000,
                "media": [{"type": "text", "text": f"Пост {tid}"}],
                "like_summary": {"count": 3},
                "discussion_summary": {"comments_count": 1},
            }
            for tid in topic_ids
        ]

    def fetch_all_comments(self, topic_id, *, max_comments=500):
        return [{"id": f"c{topic_id}", "text": "Коммент", "created_ms": 1_700_000_100_000}]


class FakeRepo:
    def __init__(self):
        self.saved_topics = []
        self.metrics = {}
        self.comments_saved = 0
        self.committed = False

    async def get_or_create_ok_network(self):
        return Obj(code="ok")

    async def resolve_organization(self, user):
        return Obj(name="org")

    async def get_or_create_public(self, org, name, description):
        return Obj(name=name)

    async def get_or_create_social_link(self, public, network, *, url, external_public_id, title):
        return Obj(url=url, external_public_id=external_public_id)

    async def upsert_topic_with_publication(self, *, org, public, link, user, group_id, topic):
        self.saved_topics.append(topic["id"])
        return Obj(), Obj(topic_id=topic["id"])

    async def upsert_post_metric(self, publication, topic, stats):
        self.metrics[publication.topic_id] = stats

    async def upsert_comments(self, publication, ok_comments):
        saved = len(list(ok_comments))
        self.comments_saved += saved
        return saved

    async def upsert_public_metric(self, link, **kw):
        self.public_metric = kw

    async def add_ingest_audit_log(self, **kw):
        pass

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


@pytest.fixture()
def service_and_deps():
    api = FakeApiClient()
    repo = FakeRepo()
    service = OkIngestionService(repository=repo, api_client=api, link_parser=OkLinkParser())
    user = Obj(organization_id=uuid.uuid4())
    return service, api, repo, user


async def test_group_restriction_falls_back_to_public_feed(service_and_deps):
    service, api, repo, user = service_and_deps

    result = await service.ingest_link(user, f"https://ok.ru/group/{GID}", max_posts=5)

    assert result.posts_imported == 2
    assert repo.saved_topics == ["111", "222"]
    assert repo.committed
    # Фолбэк получил и id группы, и shortname, и лимит.
    assert api.public_feed_calls == [{"group_id": GID, "shortname": "testgrp", "max_topics": 5}]
    # Метрики взяты из самих тем (like_summary/discussion_summary).
    assert repo.metrics["111"].likes == 3
    assert repo.metrics["111"].comments == 1
    # Пользователь предупреждён, что просмотров/охвата не будет.
    assert any("публичной ленты" in n for n in (result.notes or []))


async def test_fallback_feed_also_unavailable_keeps_group_only(service_and_deps):
    service, api, repo, user = service_and_deps
    api.fetch_public_topic_ids = lambda *a, **k: (_ for _ in ()).throw(
        OkApiError("публичная лента группы недоступна (HTTP 403)")
    )

    result = await service.ingest_link(user, f"https://ok.ru/group/{GID}")

    assert result.posts_imported == 0
    assert repo.committed  # паблик и ссылка всё равно сохранены
    assert any("VALUABLE_ACCESS" in n for n in (result.notes or []))


async def test_other_stat_errors_still_raise(service_and_deps):
    service, api, repo, user = service_and_deps

    def _param_error(gid, **kwargs):
        raise OkApiError("PARAM", code=100)

    api.fetch_all_stat_topics = _param_error

    from backend.modules.ok.utils.errors import OkIngestionError

    with pytest.raises(OkIngestionError, match="getStatTopics"):
        await service.ingest_link(user, f"https://ok.ru/group/{GID}")


async def test_date_filter_applied_to_public_feed_topics(service_and_deps):
    from datetime import datetime, timezone

    service, api, repo, user = service_and_deps

    def _mediatopics(topic_ids):
        # 111 — свежая тема, 222 — старая (за границей периода).
        by_id = {
            "111": 1_700_000_000_000,
            "222": 1_500_000_000_000,
        }
        return [
            {"id": tid, "created_ms": by_id[tid], "media": [{"type": "text", "text": "x"}]}
            for tid in topic_ids
        ]

    api.get_mediatopics = _mediatopics

    result = await service.ingest_link(
        user,
        f"https://ok.ru/group/{GID}",
        date_from=datetime(2023, 1, 1, tzinfo=timezone.utc),
        fetch_comments=False,
    )

    assert repo.saved_topics == ["111"]
    assert result.posts_imported == 1
