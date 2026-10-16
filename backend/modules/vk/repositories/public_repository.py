"""Репозиторий VK-паблика."""

from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.db import SocialNetwork, User, PublicSocialLink, Public
from backend.modules.vk.utils.constants import AUTO_DEFAULT_PUBLIC_DESCRIPTION


class VkPublicRepository:
    """Инкапсулирует SQL-запросы для выбора дефолтного VK-паблика."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_vk_network(self) -> SocialNetwork | None:
        """Возвращает социальную сеть VK из справочника."""

        result = await self.db.execute(select(SocialNetwork).where(SocialNetwork.code == "vk"))
        return result.scalar_one_or_none()

    def base_active_links_stmt(self, user: User):
        """Строит базовый select активных VK-ссылок организации."""

        return (
            select(PublicSocialLink)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .where(Public.organization_id == user.organization_id)
            .where(PublicSocialLink.is_active.is_(True))
            .where(SocialNetwork.code == "vk")
        )

    async def find_by_group_id(self, user: User, group_id: int) -> PublicSocialLink | None:
        """Ищет активную VK-ссылку организации по GROUP_ID."""

        stmt = (
            self.base_active_links_stmt(user)
            .where(PublicSocialLink.external_public_id == str(group_id))
            .order_by(PublicSocialLink.is_primary.desc(), PublicSocialLink.created_at.asc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_fallback_links(self, user: User) -> Sequence[PublicSocialLink]:
        """Возвращает первые две активные VK-ссылки для fallback-логики."""

        stmt = (
            self.base_active_links_stmt(user)
            .order_by(PublicSocialLink.is_primary.desc(), PublicSocialLink.created_at.asc())
            .limit(2)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def create_missing_default_vk_public(self, *, user: User, network: SocialNetwork) -> PublicSocialLink:
        """Создаёт дефолтный паблик из GROUP_ID, сохраняя старое поведение router."""

        existing_links_result = await self.db.execute(
            select(PublicSocialLink)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(PublicSocialLink.social_network_id == network.id)
            .where(PublicSocialLink.is_active.is_(True))
        )

        for existing_link in existing_links_result.scalars().all():
            existing_link.is_primary = False

        public = Public(
            organization_id=user.organization_id,
            name=f"VK паблик {settings.GROUP_ID}",
            description=AUTO_DEFAULT_PUBLIC_DESCRIPTION,
            is_active=True,
        )

        self.db.add(public)
        await self.db.flush()

        link = PublicSocialLink(
            public_id=public.id,
            social_network_id=network.id,
            title=f"VK паблик {settings.GROUP_ID}",
            url=f"https://vk.com/club{settings.GROUP_ID}",
            external_public_id=str(settings.GROUP_ID),
            is_primary=True,
            is_active=True,
        )
        self.db.add(link)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(link)
        return link
