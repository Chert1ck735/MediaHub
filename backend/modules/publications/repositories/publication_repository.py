from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.posts import Post
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.social_networks import SocialNetwork


class PublicationRepository:
    """Отвечает только за SQL-операции модуля publications."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_active_link_for_platform(
        self,
        organization_id,
        platform: str,
    ) -> PublicSocialLink | None:
        normalized = platform.strip().lower()
        result = await self.db.execute(
            select(PublicSocialLink)
            .join(PublicSocialLink.public)
            .join(PublicSocialLink.social_network)
            .where(PublicSocialLink.is_active.is_(True))
            .where(PublicSocialLink.public.has(organization_id=organization_id))
            .where(SocialNetwork.code == normalized)
            .order_by(PublicSocialLink.is_primary.desc(), PublicSocialLink.created_at.asc())
            .options(selectinload(PublicSocialLink.social_network))
        )
        return result.scalars().first()

    async def resolve_active_link_for_user(
        self,
        organization_id,
        *,
        public_social_link_id: str | None = None,
        platform: str | None = None,
    ) -> PublicSocialLink | None:
        if public_social_link_id:
            result = await self.db.execute(
                select(PublicSocialLink)
                .join(PublicSocialLink.public)
                .where(PublicSocialLink.id == uuid.UUID(public_social_link_id))
                .where(PublicSocialLink.is_active.is_(True))
                .where(PublicSocialLink.public.has(organization_id=organization_id))
                .options(selectinload(PublicSocialLink.social_network))
            )
            return result.scalar_one_or_none()
        if platform:
            return await self.resolve_active_link_for_platform(organization_id, platform)
        return None

    async def get_for_organization(
        self,
        publication_id: str,
        organization_id,
    ) -> Publication | None:
        result = await self.db.execute(
            select(Publication)
            .join(Publication.post)
            .where(Publication.id == uuid.UUID(publication_id))
            .where(Post.organization_id == organization_id)
            .options(
                selectinload(Publication.post)
                .selectinload(Post.publications)
                .selectinload(Publication.public_social_link)
                .selectinload(PublicSocialLink.social_network),
                selectinload(Publication.post).selectinload(Post.strategy_links),
            )
        )
        return result.scalar_one_or_none()
