"""Удаление импортированной VK-площадки.

Сервис отвечает только за сценарий удаления одного Public со связанными
публикациями/комментариями/постами и последующее обновление аналитики.
"""
import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User, Public, PublicSocialLink, Publication, Comment, Post
from backend.modules.analytics.services.analytics_refresh_service import AnalyticsRefreshService


class ImportedPublicDeleteService:
    """Удаляет одну импортированную площадку и пересобирает VK-аналитику."""

    def __init__(self, db: AsyncSession) -> None:
        """Сохраняет сессию БД."""
        self._db = db

    async def delete_public(self, user: User, public_id: str) -> dict[str, int | bool]:
        """Удаляет Public организации и возвращает статистику удаления."""
        db = self._db
        public_uuid = uuid.UUID(public_id)
        public = (
            await db.execute(
                select(Public)
                .where(Public.id == public_uuid)
                .where(Public.organization_id == user.organization_id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if public is None:
            raise ValueError("Площадка не найдена")

        link_rows = await db.execute(
            select(PublicSocialLink.id).where(PublicSocialLink.public_id == public_uuid)
        )
        link_ids = [row[0] for row in link_rows.all()]

        deleted_publications = 0
        deleted_comments = 0
        if link_ids:
            deleted_publications = int(
                (
                    await db.execute(
                        select(func.count(Publication.id)).where(
                            Publication.public_social_link_id.in_(link_ids)
                        )
                    )
                ).scalar()
                or 0
            )
            deleted_comments = int(
                (
                    await db.execute(
                        select(func.count(Comment.id))
                        .select_from(Comment)
                        .join(Publication, Publication.id == Comment.publication_id)
                        .where(Publication.public_social_link_id.in_(link_ids))
                    )
                ).scalar()
                or 0
            )

        posts_result = await db.execute(select(Post).where(Post.public_id == public_uuid))
        posts = list(posts_result.scalars().all())
        for post in posts:
            await db.delete(post)

        await db.delete(public)
        await db.flush()
        await AnalyticsRefreshService(db).refresh(user)

        return {
            "deleted_links": len(link_ids),
            "deleted_publications": deleted_publications,
            "deleted_comments": deleted_comments,
            "deleted_posts": len(posts),
            "snapshot_rebuilt": True,
        }
