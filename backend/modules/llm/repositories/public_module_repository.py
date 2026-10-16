import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.publics import Public
from backend.db.public_social_links import PublicSocialLink


class InvalidPublicSocialLinkId(ValueError):
    """Исключение для идентификатора публичной ссылки, который нельзя разобрать."""

    pass


class PublicSocialLinkNotFound(LookupError):
    """Исключение для публичной ссылки вне текущей организации."""

    pass


class PublicModuleRepository:
    """Читает контекст модулей, связанных с публичными ссылками организации."""

    def __init__(self, db: AsyncSession):
        """Сохраняет сессию БД для методов репозитория."""

        self.db = db

    async def list_for_public_link(
        self,
        *,
        public_social_link_id: str | None,
        organization_id: uuid.UUID | None,
    ) -> list[dict[str, Any]]:
        """Возвращает данные модуля генерации для выбранной публичной ссылки."""

        if not public_social_link_id or not organization_id:
            return []

        try:
            link_uuid = uuid.UUID(public_social_link_id)
        except ValueError as exc:
            raise InvalidPublicSocialLinkId("Invalid public_social_link_id") from exc

        result = await self.db.execute(
            select(PublicSocialLink)
            .where(PublicSocialLink.id == link_uuid)
            .where(PublicSocialLink.public.has(organization_id=organization_id))
            .options(selectinload(PublicSocialLink.public).selectinload(Public.module))
        )
        link = result.scalar_one_or_none()
        if link is None:
            raise PublicSocialLinkNotFound(
                "Selected public was not found for current organization"
            )

        module = getattr(link.public, "module", None)
        if module is None:
            return []

        return [
            {
                "name": module.name,
                "goal": module.goal,
                "description": module.description,
                "configuration": module.configuration or {},
            }
        ]

    async def get_generation_context(
        self,
        *,
        public_social_link_id: str,
        organization_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """Читает данные паблика для промпта генерации.

        Описание берётся из базы, а не из браузера: так сгенерировать можно только
        от имени паблика своей организации.
        """

        if not organization_id:
            raise PublicSocialLinkNotFound("Current user has no organization")

        try:
            link_uuid = uuid.UUID(public_social_link_id)
        except ValueError as exc:
            raise InvalidPublicSocialLinkId("Invalid public_social_link_id") from exc

        result = await self.db.execute(
            select(PublicSocialLink)
            .where(PublicSocialLink.id == link_uuid)
            .where(PublicSocialLink.public.has(organization_id=organization_id))
            .options(selectinload(PublicSocialLink.public))
        )
        link = result.scalar_one_or_none()
        if link is None:
            raise PublicSocialLinkNotFound(
                "Selected public was not found for current organization"
            )

        public = link.public
        return {
            "name": (link.title or public.name or "").strip(),
            "description": (public.description or "").strip()[:4_000],
            "audience": (public.audience_description or "").strip()[:2_000],
            "goal": (public.goal or "").strip()[:2_000],
        }
