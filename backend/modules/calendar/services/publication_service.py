"""Сервис публикаций календаря."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Publication, Post
from backend.modules.calendar.services.vk_sync_service import CalendarVkSyncService
from backend.modules.calendar.utils.errors import CalendarValidationError
from backend.modules.calendar.utils.interfaces import CalendarRepositoryProtocol
from backend.modules.calendar.utils.utils import unique_ids
from backend.modules.publications.service import resolve_public_social_link_for_platform
from backend.modules.posts import service as posts_service


class CalendarPublicationService:
    """Создает, обновляет, синхронизирует и удаляет публикации календаря."""

    def __init__(
        self,
        db: AsyncSession,
        repository: CalendarRepositoryProtocol,
        vk_sync_service: CalendarVkSyncService | None = None,
    ) -> None:
        self.db = db
        self.repository = repository
        self.vk_sync_service = vk_sync_service or CalendarVkSyncService()

    async def resolve_target_link_ids(
        self,
        organization_id,
        platforms: list[str],
        public_social_link_ids: list[str] | None,
    ) -> list[str]:
        """Определяет целевые public_social_link_ids по id или платформам."""

        explicit_ids = unique_ids(public_social_link_ids)
        if explicit_ids:
            return explicit_ids

        resolved: list[str] = []
        for platform in platforms:
            link = await resolve_public_social_link_for_platform(
                self.db,
                organization_id,
                platform.strip().lower(),
            )
            if not link:
                raise CalendarValidationError(
                    f"Для площадки {platform} не найдена активная public_social_link"
                )
            resolved.append(str(link.id))

        return unique_ids(resolved)

    async def upsert_publications(
        self,
        *,
        post: Post,
        organization_id,
        desired_link_ids: list[str],
        ev_status: str,
        when: datetime,
    ) -> None:
        """Создает или обновляет публикации без удаления лишних."""

        existing_by_link_id = {
            str(publication.public_social_link_id): publication
            for publication in list(post.__dict__.get("publications") or [])
        }

        for link_id in desired_link_ids:
            publication = existing_by_link_id.get(link_id)
            if publication is None:
                publication = await self._create_publication(
                    post=post,
                    organization_id=organization_id,
                    link_id=link_id,
                    ev_status=ev_status,
                    when=when,
                )
            else:
                await self._update_publication(
                    publication=publication,
                    organization_id=organization_id,
                    link_id=link_id,
                    ev_status=ev_status,
                    when=when,
                )
            self.vk_sync_service.sync_scheduled_publication(publication, post)

    async def sync_publications(
        self,
        *,
        post: Post,
        organization_id,
        desired_link_ids: list[str],
        ev_status: str,
        when: datetime,
    ) -> None:
        """Синхронизирует публикации поста с выбранными площадками."""

        existing_publications = list(post.__dict__.get("publications") or [])
        existing_by_link_id = {
            str(publication.public_social_link_id): publication
            for publication in existing_publications
        }
        desired = set(desired_link_ids)

        await self.upsert_publications(
            post=post,
            organization_id=organization_id,
            desired_link_ids=desired_link_ids,
            ev_status=ev_status,
            when=when,
        )

        for link_id, publication in existing_by_link_id.items():
            if link_id not in desired:
                self.vk_sync_service.delete_scheduled_publication(publication)
                await self.repository.delete_publication(publication)

    async def delete_publications(self, post: Post) -> None:
        """Удаляет все публикации поста."""

        for publication in list(post.__dict__.get("publications") or []):
            self.vk_sync_service.delete_scheduled_publication(publication)
            await self.repository.delete_publication(publication)

    async def _create_publication(
        self,
        *,
        post: Post,
        organization_id,
        link_id: str,
        ev_status: str,
        when: datetime,
    ) -> Publication:
        """Создает публикацию для выбранной площадки."""

        link = await self.repository.get_public_social_link(link_id, organization_id)
        if not link:
            raise CalendarValidationError("Не найдена активная public_social_link")

        publication = Publication(
            post=post,
            public_social_link_id=link.id,
            status=posts_service.PublicationStatusEnum(ev_status),
            content_type=posts_service.ContentTypeEnum.text,
            scheduled_at=when,
        )
        await self.repository.add_publication(publication)
        publication.public_social_link = link
        return publication

    async def _update_publication(
        self,
        *,
        publication: Publication,
        organization_id,
        link_id: str,
        ev_status: str,
        when: datetime,
    ) -> None:
        """Обновляет публикацию для выбранной площадки."""

        publication.status = posts_service.PublicationStatusEnum(ev_status)
        publication.scheduled_at = when
        if publication.__dict__.get("public_social_link") is None:
            publication.public_social_link = await self.repository.get_public_social_link(
                link_id,
                organization_id,
            )
