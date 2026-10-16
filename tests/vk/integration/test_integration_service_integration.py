from types import SimpleNamespace

import pytest

from backend.modules.vk.dto.dto import VkLinkType
from backend.modules.vk.links.link_parser import VkLinkParser
from backend.modules.vk.services.ingestion_service import VkIngestionService
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService


class FakeVkApiClient:
    def resolve_screen_name(self, screen_name):
        return {"type": "group", "object_id": 123}

    def get_group(self, group_ref):
        return {
            "id": 123,
            "screen_name": "test_group",
            "name": "Test Group",
            "description": "VK group description",
            "members_count": 1000,
        }

    def get_user(self, user_id):
        return {
            "id": int(user_id),
            "screen_name": f"id{user_id}",
            "first_name": "Ivan",
            "last_name": "Petrov",
            "about": "Profile about",
            "is_closed": False,
            "can_access_closed": True,
        }

    def fetch_all_wall(self, *, owner_id=None, domain=None, max_posts=100, date_from=None, date_to=None, on_progress=None):
        return [
            {"id": 1, "owner_id": owner_id, "date": 1_700_000_000, "text": "First", "views": {"count": 10}, "likes": {"count": 2}, "comments": {"count": 1}, "reposts": {"count": 0}},
            {"id": 2, "owner_id": owner_id, "date": 1_700_000_001, "text": "Second", "views": {"count": 20}, "likes": {"count": 3}, "comments": {"count": 0}, "reposts": {"count": 1}},
        ][:max_posts]

    def wall_get_by_id(self, owner_id, post_id):
        return {"id": post_id, "owner_id": owner_id, "date": 1_700_000_000, "text": "Single", "views": {"count": 7}, "likes": {"count": 1}, "comments": {"count": 1}, "reposts": {"count": 0}}

    def fetch_all_comments(self, owner_id, post_id, *, max_comments=500):
        return [{"id": post_id * 100, "text": "comment", "from_id": 1, "date": 1_700_000_100}]


class FakeRepository:
    def __init__(self):
        self.org = SimpleNamespace(id="org")
        self.network = SimpleNamespace(id="vk-network")
        self.public = SimpleNamespace(id="public")
        self.link = SimpleNamespace(id="link")
        self.posts = []
        self.comments = []
        self.metrics = []
        self.public_metrics = []
        self.audit = []
        self.committed = False

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
        publication = SimpleNamespace(id=f"publication-{vk_post['id']}")
        self.posts.append(vk_post)
        return SimpleNamespace(id=f"post-{vk_post['id']}"), publication

    async def upsert_post_metric(self, publication, vk_post):
        self.metrics.append((publication.id, vk_post["id"]))

    async def upsert_comments(self, publication, vk_comments):
        self.comments.extend(vk_comments)
        return len(vk_comments)

    async def upsert_public_metric(self, link, **kwargs):
        self.public_metrics.append(kwargs)

    async def add_ingest_audit_log(self, **kwargs):
        self.audit.append(kwargs)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_ingest_screen_name_community_full_flow():
    repo = FakeRepository()
    api_client = FakeVkApiClient()
    service = VkIngestionService(
        repository=repo,
        api_client=api_client,
        link_parser=VkLinkParser(),
        owner_resolver=VkOwnerResolverService(api_client),
    )

    result = await service.ingest_link(SimpleNamespace(id="user"), "https://vk.com/test_group", max_posts=2, fetch_comments=True)

    assert result.type == VkLinkType.COMMUNITY
    assert result.canonical_url == "https://vk.com/test_group"
    assert result.posts_imported == 2
    assert result.comments_imported == 1
    assert repo.public_metrics == [{
        "members": 1000,
        "posts_total": 2,
        "sum_views": 30,
        "sum_likes": 5,
        "sum_comments": 1,
        "sum_reposts": 1,
    }]
    assert repo.audit[0]["mode"] == "community"
    assert repo.committed is True


@pytest.mark.asyncio
async def test_ingest_single_post_full_flow():
    repo = FakeRepository()
    api_client = FakeVkApiClient()
    service = VkIngestionService(
        repository=repo,
        api_client=api_client,
        link_parser=VkLinkParser(),
        owner_resolver=VkOwnerResolverService(api_client),
    )

    result = await service.ingest_link(SimpleNamespace(id="user"), "https://vk.com/wall-123_456", fetch_comments=True)

    assert result.type == VkLinkType.POST
    assert result.posts_imported == 1
    assert result.publications_imported == 1
    assert result.comments_imported == 1
    assert repo.posts[0]["id"] == 456
    assert repo.audit[0]["mode"] == "single_post"
    assert repo.committed is True
