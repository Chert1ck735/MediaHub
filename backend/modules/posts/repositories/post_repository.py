"""Репозиторий posts.

Здесь живут только SQL-запросы для загрузки, добавления и удаления постов.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.enums import PostOriginEnum
from backend.db.posts import Post
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication


class PostRepository:
    """Отвечает только за операции с Post в БД."""

    def __init__(self, db: AsyncSession):
        """Сохраняет session, через которую выполняются запросы."""
        self.db = db

    async def get_for_organization(
        self,
        post_id: str,
        organization_id,
        *,
        with_publications: bool = True,
    ) -> Post | None:
        """Загружает пост организации с нужными связями."""
        try:
            post_uuid = uuid.UUID(post_id)
        except (ValueError, TypeError):
            return None

        options = [selectinload(Post.strategy_links)]
        if with_publications:
            options.append(
                selectinload(Post.publications)
                .selectinload(Publication.public_social_link)
                .selectinload(PublicSocialLink.social_network)
            )
        result = await self.db.execute(
            select(Post)
            .where(Post.id == post_uuid, Post.organization_id == organization_id)
            .options(*options)
        )
        return result.scalar_one_or_none()

    async def list_editor_posts(self, organization_id) -> list[Post]:
        """Возвращает ручные и LLM-посты организации для редактора."""
        result = await self.db.execute(
            select(Post)
            .where(Post.organization_id == organization_id)
            .where(Post.origin.in_([PostOriginEnum.manual, PostOriginEnum.llm_generated]))
            .order_by(Post.created_at.desc())
            .options(
                selectinload(Post.publications)
                .selectinload(Publication.public_social_link)
                .selectinload(PublicSocialLink.social_network),
                selectinload(Post.strategy_links),
            )
        )
        return list(result.scalars().all())

    async def add(self, post: Post) -> Post:
        """Добавляет пост в текущую транзакцию."""
        self.db.add(post)
        return post

    async def delete(self, post: Post) -> None:
        """Помечает пост на удаление в текущей транзакции."""
        await self.db.delete(post)
