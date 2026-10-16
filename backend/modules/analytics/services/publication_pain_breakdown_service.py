"""Разбивка публикации по болям."""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.publication_repository import PublicationRepository
from backend.modules.analytics.schemas import PublicationPainBucket


class PublicationPainBreakdownService:
    """Считает, в какие боли разошлись комментарии одной публикации."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        publication_repository: PublicationRepository | None = None,
    ) -> None:
        self._db = db
        self._repo = publication_repository or PublicationRepository(db)

    async def get_breakdown(
        self,
        user: User,
        *,
        url: str | None = None,
        publication_id: str | None = None,
    ) -> list[PublicationPainBucket]:
        """Возвращает breakdown по publication_id или url."""

        if not (publication_id or url):
            raise ValueError("Нужен publication_id или url")

        publication_uuid = await self._repo.resolve_publication_id(
            user,
            publication_id=publication_id,
            url=url,
        )
        if publication_uuid is None:
            raise LookupError("Публикация не найдена")

        rows = await self._repo.list_pain_breakdown_for_publication(publication_uuid, user)
        return [
            PublicationPainBucket(
                pain_id=str(pain_id),
                pain_title=title,
                pain_category=category,
                comments_count=int(count),
            )
            for pain_id, title, category, count in rows
        ]
