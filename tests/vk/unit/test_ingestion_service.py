from types import SimpleNamespace

import pytest

from backend.modules.vk.dto.dto import VkLinkRef, VkLinkType, VkOwnerInfoDTO
from backend.modules.vk.services.ingestion_service import VkIngestionService
from backend.modules.vk.utils.errors import InvalidVkLinkError, IngestionError, VkApiError


class FakeLinkParser:
    def __init__(self, ref=None, error=None):
        self.ref = ref
        self.error = error

    def parse(self, raw):
        if self.error:
            raise self.error
        return self.ref

class FakeOwnerResolver:
    def __init__(self, owner):
        self.owner = owner
        self.resolve_screen_name_called = False

    def resolve_screen_name(self, ref):
        self.resolve_screen_name_called = True
        return VkLinkRef(
            type=VkLinkType.COMMUNITY,
            raw_url=ref.raw_url,
            canonical_url=ref.canonical_url,
            owner_id=-123,
            screen_name=ref.domain,
        )

    def resolve_community_owner(self, ref):
        return self.owner

    def resolve_profile_owner(self, ref):
        return self.owner

    def resolve_post_owner(self, ref):
        return self.owner

class FakeApiClient:
    def __init__(self):
        self.posts = []
        self.comments = []
        self.post_by_id = None
        self.wall_error = None
        self.comments_error = None

    def fetch_all_wall(self, **kwargs):
        if self.wall_error:
            raise self.wall_error
        return self.posts

    def wall_get_by_id(self, owner_id, post_id):
        if self.wall_error:
            raise self.wall_error
        return self.post_by_id

    def fetch_all_comments(self, owner_id, post_id, *, max_comments=500):
        if self.comments_error:
            raise self.comments_error
        return self.comments

class FakeRepository:
    def __init__(self):
        self.org = SimpleNamespace(id="org-1")
        self.network = SimpleNamespace(id="network-1")
        self.public = SimpleNamespace(id="public-1")
        self.link = SimpleNamespace(id="link-1")
        self.public_metrics = []
        self.post_metrics = []
        self.saved_posts = []
        self.saved_comments = []
        self.audit_logs = []
        self.commits = 0
        self.rollbacks = 0

    async def resolve_organization(self, user):
        return self.org

    async def get_or_create_vk_network(self):
        return self.network

    async def get_or_create_public(self, org, name, description):
        self.public.name = name
        self.public.description = description
        return self.public

    async def get_or_create_social_link(self, public, network, *, url, external_public_id, title):
        self.link.url = url
        self.link.external_public_id = external_public_id
        self.link.title = title
        return self.link

    async def upsert_post_with_publication(self, *, org, public, link, user, vk_post):
        self.saved_posts.append(vk_post)
        return SimpleNamespace(id=f"post-{len(self.saved_posts)}"), SimpleNamespace(id=f"publication-{len(self.saved_posts)}")

    async def upsert_post_metric(self, publication, vk_post):
        self.post_metrics.append((publication, vk_post))

    async def upsert_comments(self, publication, vk_comments):
        self.saved_comments.extend(vk_comments)
        return len(vk_comments)

    async def upsert_public_metric(self, link, **kwargs):
        self.public_metrics.append(kwargs)

    async def add_ingest_audit_log(self, **kwargs):
        self.audit_logs.append(kwargs)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class FakeAnalyticsRefreshService:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    async def refresh(self, user):
        self.calls += 1
        if self.error:
            raise self.error


def make_owner(**overrides):
    data = dict(
        name="Test Owner",
        description="Description",
        screen="test_owner",
        canonical_url="https://vk.com/test_owner",
        external_public_id="123",
        owner_id=-123,
        members_count=100,
        is_closed=False,
        can_access_closed=True,
    )
    data.update(overrides)
    return VkOwnerInfoDTO(**data)

@pytest.mark.asyncio
async def test_ingest_link_wraps_invalid_link_error():
    service = VkIngestionService(
        repository=FakeRepository(),
        api_client=FakeApiClient(),
        link_parser=FakeLinkParser(error=InvalidVkLinkError("bad link")),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )

    with pytest.raises(IngestionError, match="bad link"):
        await service.ingest_link(SimpleNamespace(), "bad")

@pytest.mark.asyncio
async def test_ingest_community_imports_posts_metrics_comments_and_commits():
    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = [
        {"id": 1, "owner_id": -123, "date": 1_700_000_000, "text": "one", "views": {"count": 10}, "likes": {"count": 2}, "comments": {"count": 1}, "reposts": {"count": 3}},
        {"id": 2, "owner_id": -123, "date": 1_700_000_001, "text": "two", "views": {"count": 20}, "likes": {"count": 4}, "comments": {"count": 0}, "reposts": {"count": 1}},
    ]
    api.comments = [{"id": 100, "text": "comment"}]
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    analytics = FakeAnalyticsRefreshService()
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
        analytics_refresh_service=analytics,
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/club123", max_posts=2, fetch_comments=True)

    assert result.type == VkLinkType.COMMUNITY
    assert result.posts_imported == 2
    assert result.comments_imported == 1
    assert repo.public_metrics[0] == {
        "members": 100,
        "posts_total": 2,
        "sum_views": 30,
        "sum_likes": 6,
        "sum_comments": 1,
        "sum_reposts": 4,
    }
    assert repo.commits == 1
    assert analytics.calls == 1

@pytest.mark.asyncio
async def test_ingest_post_without_comments():
    repo = FakeRepository()
    api = FakeApiClient()
    api.post_by_id = {"id": 456, "owner_id": -123, "date": 1_700_000_000, "text": "single"}
    ref = VkLinkRef(type=VkLinkType.POST, raw_url="vk.com/wall-123_456", canonical_url="https://vk.com/wall-123_456", owner_id=-123, post_id=456)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/wall-123_456", fetch_comments=False)

    assert result.type == VkLinkType.POST
    assert result.posts_imported == 1
    assert result.comments_imported == 0
    assert len(repo.saved_posts) == 1
    assert repo.commits == 1


@pytest.mark.asyncio
async def test_ingest_profile_saves_followers_as_public_metric_members():
    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = [
        {"id": 1, "owner_id": 42, "date": 1_700_000_000, "text": "one", "views": {"count": 10}, "likes": {"count": 2}, "comments": {"count": 1}, "reposts": {"count": 3}},
    ]
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner(owner_id=42, members_count=77)),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/id42", max_posts=1, fetch_comments=False)

    assert result.type == VkLinkType.PROFILE
    assert result.posts_imported == 1
    assert repo.public_metrics[0]["members"] == 77


@pytest.mark.asyncio
async def test_private_profile_returns_empty_result_and_note():
    repo = FakeRepository()
    api = FakeApiClient()
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner(owner_id=42, members_count=77, is_closed=True, can_access_closed=False)),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/id42")

    assert result.type == VkLinkType.PROFILE
    assert result.posts_imported == 0
    assert result.comments_imported == 0
    assert result.notes == ["Профиль закрыт. Стена и комментарии не импортируются."]
    assert repo.public_metrics[0]["members"] == 77
    assert repo.commits == 1


@pytest.mark.asyncio
async def test_profile_private_vk_api_code_returns_empty_result():
    repo = FakeRepository()
    api = FakeApiClient()
    api.wall_error = VkApiError("private", code=15)
    ref = VkLinkRef(type=VkLinkType.PROFILE, raw_url="vk.com/id42", canonical_url="https://vk.com/id42", owner_id=42)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner(owner_id=42, members_count=77)),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/id42")

    assert result.posts_imported == 0
    assert "Стена профиля недоступна" in result.notes[0]
    assert repo.public_metrics[0]["members"] == 77
    assert repo.commits == 1


@pytest.mark.asyncio
async def test_comments_load_error_is_note_not_failed_import():
    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = [{"id": 1, "owner_id": -123, "date": 1_700_000_000, "text": "one", "comments": {"count": 1}}]
    api.comments_error = VkApiError("comments denied", code=15)
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/club123")

    assert result.posts_imported == 1
    assert result.comments_imported == 0
    assert "Не удалось забрать комментарии поста 1" in result.notes[0]


@pytest.mark.asyncio
async def test_analytics_refresh_error_rollbacks_and_adds_note():
    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = []
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
        analytics_refresh_service=FakeAnalyticsRefreshService(error=RuntimeError("boom")),
    )

    result = await service.ingest_link(SimpleNamespace(), "vk.com/club123")

    assert repo.commits == 1
    assert repo.rollbacks == 1
    assert any("Автоаналитика комментариев не обновилась" in note for note in result.notes)


class FakeReporter:
    """Перехватывает прогресс и умеет имитировать запрос отмены."""

    def __init__(self, cancel_after=None):
        self.updates = []
        self.cancel_after = cancel_after
        self._seen = 0

    async def update(self, *, total=None, done=None, message=None):
        self.updates.append({"total": total, "done": done, "message": message})

    def update_sync(self, *, total=None, done=None, message=None):
        self.updates.append({"total": total, "done": done, "message": message})

    async def inc(self, *, by=1, message=None):
        self.updates.append({"inc": by, "message": message})

    def is_cancelled(self):
        return self.cancel_after is not None and self._seen >= self.cancel_after

    def raise_if_cancelled(self):
        from backend.modules.jobs.models import JobCancelled

        self._seen += 1
        if self.is_cancelled():
            raise JobCancelled()


@pytest.mark.asyncio
async def test_ingest_reports_progress_total_and_done():
    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = [
        {"id": 1, "owner_id": -123, "date": 1_700_000_000, "text": "one", "comments": {"count": 1}},
        {"id": 2, "owner_id": -123, "date": 1_700_000_001, "text": "two", "comments": {"count": 0}},
    ]
    api.comments = [{"id": 100, "text": "c"}]
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )
    reporter = FakeReporter()

    await service.ingest_link(SimpleNamespace(), "vk.com/club123", fetch_comments=True, reporter=reporter)

    totals = [u["total"] for u in reporter.updates if u.get("total") is not None]
    dones = [u["done"] for u in reporter.updates if u.get("done") is not None]
    # Фаза постов задаёт total=2, фаза комментариев расширяет шкалу до 2+1.
    assert 2 in totals and 3 in totals
    assert max(dones) == 3


@pytest.mark.asyncio
async def test_ingest_aborts_on_cancel_request():
    from backend.modules.jobs.models import JobCancelled

    repo = FakeRepository()
    api = FakeApiClient()
    api.posts = [
        {"id": i, "owner_id": -123, "date": 1_700_000_000 + i, "text": str(i)} for i in range(1, 6)
    ]
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )
    reporter = FakeReporter(cancel_after=2)

    with pytest.raises(JobCancelled):
        await service.ingest_link(SimpleNamespace(), "vk.com/club123", reporter=reporter)

    # Импорт прерван до сохранения всех 5 постов.
    assert len(repo.saved_posts) < 5


class PaginatingApiClient(FakeApiClient):
    """fetch_all_wall, который зовёт on_progress по страницам — для теста прогресса стены."""

    def __init__(self, pages):
        super().__init__()
        self._pages = pages

    def fetch_all_wall(self, *, on_progress=None, **kwargs):
        if self.wall_error:
            raise self.wall_error
        collected = []
        total = sum(len(p) for p in self._pages)
        for page in self._pages:
            collected.extend(page)
            if on_progress is not None:
                on_progress(len(collected), total)
        self.posts = collected
        return collected


@pytest.mark.asyncio
async def test_wall_fetch_reports_pagination_progress():
    pages = [
        [{"id": 1, "owner_id": -123, "date": 1}, {"id": 2, "owner_id": -123, "date": 2}],
        [{"id": 3, "owner_id": -123, "date": 3}],
    ]
    api = PaginatingApiClient(pages)
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=FakeRepository(),
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )
    reporter = FakeReporter()

    await service.ingest_link(SimpleNamespace(), "vk.com/club123", fetch_comments=False, reporter=reporter)

    msgs = [u["message"] for u in reporter.updates if u.get("message")]
    # Прогресс стены отрепортился постранично: 2/3, затем 3/3.
    assert any("2/3" in m for m in msgs)
    assert any("3/3" in m for m in msgs)


@pytest.mark.asyncio
async def test_wall_fetch_aborts_on_cancel_between_pages():
    from backend.modules.jobs.models import JobCancelled

    pages = [[{"id": i, "owner_id": -123, "date": i}] for i in range(1, 6)]
    api = PaginatingApiClient(pages)
    ref = VkLinkRef(type=VkLinkType.COMMUNITY, raw_url="vk.com/club123", canonical_url="https://vk.com/club123", owner_id=-123)
    service = VkIngestionService(
        repository=FakeRepository(),
        api_client=api,
        link_parser=FakeLinkParser(ref),
        owner_resolver=FakeOwnerResolver(make_owner()),
    )
    reporter = FakeReporter(cancel_after=1)

    with pytest.raises(JobCancelled):
        await service.ingest_link(SimpleNamespace(), "vk.com/club123", reporter=reporter)
