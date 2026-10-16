"""Unit-тест оркестрации VkIngestionService._save_posts (без сети и БД).

Фиксирует поведение сохранения постов и комментариев перед оптимизацией
парсинга (параллельный фетч). api_client и repository — заглушки.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.modules.vk.services.ingestion_service import VkIngestionService


class _FakeApiClient:
    def __init__(self, comments_by_post: dict[int, list]):
        self._comments = comments_by_post
        self.fetch_calls: list[int] = []

    def fetch_all_comments(self, owner_id, post_id, *, max_comments=500):
        self.fetch_calls.append(post_id)
        return self._comments.get(post_id, [])


class _FakeRepo:
    def __init__(self):
        self.saved_comments: dict[int, int] = {}

    async def upsert_post_with_publication(self, *, org, public, link, user, vk_post):
        publication = SimpleNamespace(id=vk_post["id"])
        return SimpleNamespace(), publication

    async def upsert_post_metric(self, publication, vk_post):
        return None

    async def upsert_comments(self, publication, vk_comments):
        n = len(list(vk_comments))
        self.saved_comments[publication.id] = n
        return n


def _post(pid: int, *, comments: int = 0, views: int = 0, likes: int = 0, reposts: int = 0):
    return {
        "id": pid,
        "comments": {"count": comments},
        "views": {"count": views},
        "likes": {"count": likes},
        "reposts": {"count": reposts},
    }


def _service(api, repo):
    return VkIngestionService(
        repository=repo,
        api_client=api,
        link_parser=SimpleNamespace(parse=lambda raw: None),
    )


@pytest.mark.asyncio
async def test_save_posts_counts_and_comment_fetch():
    posts = [
        _post(1, comments=2, views=10, likes=3),
        _post(2, comments=0, views=5, likes=1),   # без комментов — фетч не нужен
        _post(3, comments=1, views=7, likes=2),
    ]
    api = _FakeApiClient({1: [{"id": 11}, {"id": 12}], 3: [{"id": 31}]})
    repo = _FakeRepo()
    service = _service(api, repo)

    stats = await service._save_posts(
        user=SimpleNamespace(),
        organization=SimpleNamespace(),
        public=SimpleNamespace(),
        link=SimpleNamespace(),
        posts=posts,
        owner_id=-100,
        fetch_comments=True,
        notes=[],
    )

    assert stats["publications"] == 3
    assert stats["saved_comments"] == 3          # 2 + 0 + 1
    assert stats["views"] == 22
    assert stats["likes"] == 6
    # комменты тянули только у постов с count>0
    assert set(api.fetch_calls) == {1, 3}
    assert repo.saved_comments == {1: 2, 3: 1}


@pytest.mark.asyncio
async def test_save_posts_skips_fetch_when_disabled():
    posts = [_post(1, comments=5)]
    api = _FakeApiClient({1: [{"id": 11}]})
    repo = _FakeRepo()
    service = _service(api, repo)

    stats = await service._save_posts(
        user=SimpleNamespace(),
        organization=SimpleNamespace(),
        public=SimpleNamespace(),
        link=SimpleNamespace(),
        posts=posts,
        owner_id=-100,
        fetch_comments=False,
        notes=[],
    )

    assert stats["publications"] == 1
    assert stats["saved_comments"] == 0
    assert api.fetch_calls == []  # фетч выключен
