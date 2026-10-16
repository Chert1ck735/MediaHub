"""Доступ к данным импортированных VK-пабликов и их публикаций."""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.pains import Pain
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.publications import Publication
from backend.db.social_networks import SocialNetwork
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.db.users import User
from backend.modules.analytics.constants import ANALYTICS_NETWORK_CODES


class PublicationRepository:
    """SQL-доступ к ``Public``, ``Publication``, ``PublicSocialLink`` и ``SocialNetwork``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_vk_public_names(self, user: User) -> list[str]:
        """Уникальные названия пабликов (VK/OK), импортированных в организацию."""

        result = await self._db.execute(
            select(Public.name)
            .join(PublicSocialLink, PublicSocialLink.public_id == Public.id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .order_by(Public.name.asc())
        )
        names = [row[0] for row in result.all() if row[0]]
        return list(dict.fromkeys(names))

    async def get_public_by_id(self, public_id: str, user: User) -> Public | None:
        """Возвращает паблик с проверкой принадлежности организации пользователя."""

        public_uuid = uuid.UUID(public_id)
        result = await self._db.execute(
            select(Public)
            .where(Public.id == public_uuid, Public.organization_id == user.organization_id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_publications_for_public(self, public_id: uuid.UUID) -> list[Publication]:
        """Все публикации указанного паблика, отсортированные по дате."""

        result = await self._db.execute(
            select(Publication)
            .where(Publication.public_id == public_id)
            .order_by(Publication.published_at.desc())
        )
        return list(result.scalars().all())

    async def resolve_publication_id(
        self,
        user: User,
        *,
        publication_id: str | None = None,
        url: str | None = None,
    ) -> uuid.UUID | None:
        """Находит ``publication.id`` по id или url с проверкой организации."""

        stmt = (
            select(Publication.id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
        )
        if publication_id:
            stmt = stmt.where(Publication.id == uuid.UUID(publication_id))
        else:
            stmt = stmt.where(Publication.url == url)
        row = (await self._db.execute(stmt)).first()
        return row[0] if row else None

    async def list_pain_breakdown_for_publication(
        self,
        publication_id: uuid.UUID,
        user: User,
    ) -> Sequence[Row]:
        """Сырой агрегат ``(pain_id, title, category, comments_count)`` по публикации."""

        # тот же скоуп обращения, что в карточках болей, — иначе разбивка
        # публикации не сходится с «упоминаниями» этих же болей
        result = await self._db.execute(
            CommentRepository.appeal_scope(
                select(
                    Pain.id,
                    Pain.title,
                    Pain.category,
                    func.count(func.distinct(Comment.id)).label("n"),
                )
                .select_from(Comment)
                .join(CommentPain, CommentPain.comment_id == Comment.id)
                .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
                .join(Pain, Pain.id == CommentPain.pain_id)
                .where(Comment.publication_id == publication_id)
                .where(Comment.is_deleted.is_(False))
                .where(Pain.organization_id == user.organization_id)
            )
            .group_by(Pain.id, Pain.title, Pain.category)
            .order_by(func.count(func.distinct(Comment.id)).desc())
        )
        return result.all()
