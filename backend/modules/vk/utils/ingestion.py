"""Тонкий compatibility-entrypoint для VK-импорта.

Основная логика находится в services/ingestion_service.py и
repositories/ingestion_repository.py.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.vk.dto.dto import IngestResult
from backend.modules.vk.links.link_parser import VkLinkParser
from backend.modules.vk.repositories.ingestion_repository import VkIngestionRepository
from backend.modules.vk.services.ingestion_service import VkIngestionService
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.api_client import VkApiClient


async def ingest_link(
    db: AsyncSession,
    user: User,
    raw_url: str,
    *,
    max_posts: int = 50,
    fetch_comments: bool = True,
) -> IngestResult:
    """Импортирует VK-ссылку через независимый VkIngestionService."""
    api_client = VkApiClient()
    service = VkIngestionService(
        repository=VkIngestionRepository(db),
        api_client=api_client,
        link_parser=VkLinkParser(),
        owner_resolver=VkOwnerResolverService(api_client),
    )
    return await service.ingest_link(user, raw_url, max_posts=max_posts, fetch_comments=fetch_comments)
