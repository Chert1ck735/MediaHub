"""Сервис чтения публичных analytics-страниц."""

from typing import Any

from backend.db import User
from backend.modules.analytics.utils.interfaces import PublicQueryRepositoryProtocol


class PublicQueryService:
    """Сценарии чтения publics/publications/comments без SQL в router."""

    def __init__(self, repository: PublicQueryRepositoryProtocol) -> None:
        self.repository = repository

    async def list_publics(self, user: User) -> list[dict[str, Any]]:
        """Возвращает импортированные площадки."""
        return await self.repository.list_publics(user)

    async def list_publications(
            self,
            user: User,
            *,
            public_social_link_id: str | None = None,
            limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Возвращает публикации организации."""
        return await self.repository.list_publications(
            user,
            public_social_link_id=public_social_link_id,
            limit=limit,
        )

    async def list_recent_comments(
            self,
            user: User,
            *,
            publication_id: str | None = None,
            limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Возвращает последние комментарии организации."""

        return await self.repository.list_recent_comments(
            user,
            publication_id=publication_id,
            limit=limit,
        )
