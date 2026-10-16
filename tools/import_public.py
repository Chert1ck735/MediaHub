"""Импорт VK-паблика напрямую, в обход фоновой джобы/прогресс-бара.

Запуск:  python -m tools.import_public <vk_url> [max_posts]
Берёт первого пользователя (его организацию), тянет стену и комментарии,
коммитит и пересобирает аналитику.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.vk.links.link_parser import VkLinkParser
from backend.modules.vk.repositories.ingestion_repository import VkIngestionRepository
from backend.modules.vk.services.ingestion_service import VkIngestionService
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.api_client import VkApiClient


class StubReporter:
    async def update(self, **kw):
        if kw.get("message"):
            print(f"  [{kw.get('done', '')}/{kw.get('total', '')}] {kw['message']}", flush=True)

    async def inc(self, **kw):
        pass

    def update_sync(self, **kw):
        if kw.get("message"):
            print(f"  [{kw.get('done', '')}/{kw.get('total', '')}] {kw['message']}", flush=True)

    def raise_if_cancelled(self):
        pass


async def main(url: str, max_posts: int | None) -> None:
    async with async_session_maker() as session:
        user = (await session.execute(select(User).limit(1))).scalar_one()
        api = VkApiClient()
        service = VkIngestionService(
            repository=VkIngestionRepository(session),
            api_client=api,
            link_parser=VkLinkParser(),
            owner_resolver=VkOwnerResolverService(api),
        )
        print(f"Импорт {url} (org={user.organization_id}, max_posts={max_posts})…", flush=True)
        result = await service.ingest_link(
            user, url, max_posts=max_posts, fetch_comments=True, reporter=StubReporter()
        )
        print(
            f"ГОТОВО: type={result.type.value} posts={result.posts_imported} "
            f"comments={result.comments_imported} url={result.canonical_url}",
            flush=True,
        )


if __name__ == "__main__":
    url = sys.argv[1]
    max_posts = int(sys.argv[2]) if len(sys.argv) > 2 else None
    asyncio.run(main(url, max_posts))
