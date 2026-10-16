"""Бизнес-сервис календарных событий."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.audit_utils import add_action_log
from backend.modules.calendar.repositories.calendar_repository import CalendarRepository
from backend.modules.calendar.serializers.serializer import CalendarEventSerializer
from backend.modules.calendar.services.post_service import CalendarPostService
from backend.modules.calendar.services.publication_service import CalendarPublicationService
from backend.modules.calendar.utils.interfaces import CalendarSerializerProtocol, CalendarPublicationServiceProtocol, \
    CalendarPostServiceProtocol, CalendarRepositoryProtocol
from backend.modules.calendar.utils.utils import schedule_dt
from backend.modules.posts import service as posts_service


class CalendarEventService:
    """Оркестрирует сценарии календаря через узкие сервисы."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        repository: CalendarRepositoryProtocol | None = None,
        post_service: CalendarPostServiceProtocol | None = None,
        publication_service: CalendarPublicationServiceProtocol | None = None,
        serializer: CalendarSerializerProtocol | None = None,
    ) -> None:
        """Собирает зависимости календарного сервиса."""
        self.db = db
        self.repository = repository or CalendarRepository(db)
        self.post_service = post_service or CalendarPostService(db, self.repository)
        self.publication_service = publication_service or CalendarPublicationService(db, self.repository)
        self.serializer = serializer or CalendarEventSerializer()

    async def list_events(
        self,
        user: User,
        *,
        date_from=None,
        date_to=None,
        link_ids=None,
        per_day=None,
        timezone_name="UTC",
        limit=None,
        offset=0,
    ) -> list[dict]:
        """Возвращает события календаря организации за окно показа.

        ``per_day`` оставляет по нескольку записей на день — столько и нужно
        сетке месяца. Полное число публикаций дня едет отдельным счётчиком.
        """
        rows = await self.repository.list_calendar_publications(
            user.organization_id, date_from=date_from, date_to=date_to,
            link_ids=link_ids, per_day=per_day, timezone_name=timezone_name,
            limit=limit, offset=offset,
        )
        event_ids = {publication.post.event_id for publication, _ in rows if publication.post.event_id}
        pain_links_by_event = await self.repository.fetch_event_pain_links_map(event_ids)

        items: list[dict] = []
        for publication, day_total in rows:
            item = self.serializer.from_post(
                publication.post, publication=publication,
                compact=per_day is not None,
                pain_links=pain_links_by_event.get(publication.post.event_id, []),
            )
            item["day_total"] = day_total
            items.append(item)
        return items

    async def create_event(
        self,
        user: User,
        *,
        title: str,
        date: str,
        description: str,
        start_time: str,
        end_time: str,
        ev_status: str,
        platforms: list[str],
        public_social_link_ids: list[str] | None = None,
        draft: str = "",
        tone: str = "",
        post_type: str = "",
        post_id: str | None = None,
        info_event_id: str | None = None,
    ) -> dict:
        """Создает календарное событие."""

        post = await self.post_service.create_or_update_post(
            user=user,
            post_id=post_id,
            title=title,
            description=description,
            draft=draft,
            tone=tone,
        )
        self.post_service.apply_info_event(post, info_event_id, reset_on_invalid=True)

        when = schedule_dt(date, start_time)
        desired_link_ids = await self.publication_service.resolve_target_link_ids(
            user.organization_id,
            platforms,
            public_social_link_ids,
        )
        await self.publication_service.upsert_publications(
            post=post,
            organization_id=user.organization_id,
            desired_link_ids=desired_link_ids,
            ev_status=ev_status,
            when=when,
        )

        await posts_service.refresh_post_rollups(self.db, post)
        add_action_log(
            self.db,
            user_id=user.id,
            action="calendar_event_created",
            entity_type="post",
            entity_id=post.id,
            details={
                "platforms": platforms,
                "public_social_link_ids": desired_link_ids,
                "post_type": post_type,
                "end_time": end_time,
            },
        )
        await self.repository.commit()

        saved_post = await self.post_service.require_post(str(post.id), user.organization_id)
        pain_links = await self.repository.fetch_event_pain_links(saved_post.event_id)
        return self.serializer.from_post(saved_post, pain_links=pain_links)

    async def update_event(
        self,
        event_id: str,
        user: User,
        *,
        title: str,
        date: str,
        description: str,
        start_time: str,
        end_time: str,
        ev_status: str,
        platforms: list[str],
        public_social_link_ids: list[str] | None = None,
        draft: str = "",
        tone: str = "",
        post_type: str = "",
        info_event_id: str | None = None,
    ) -> dict:
        """Обновляет календарное событие."""

        post = await self.post_service.require_post(event_id, user.organization_id)
        self.post_service.fill_post(
            post=post,
            title=title,
            description=description,
            draft=draft,
            tone=tone,
        )
        self.post_service.apply_info_event(post, info_event_id, reset_on_invalid=False)

        when = schedule_dt(date, start_time)
        desired_link_ids = await self.publication_service.resolve_target_link_ids(
            user.organization_id,
            platforms,
            public_social_link_ids,
        )
        await self.publication_service.sync_publications(
            post=post,
            organization_id=user.organization_id,
            desired_link_ids=desired_link_ids,
            ev_status=ev_status,
            when=when,
        )

        await self.repository.flush()
        await posts_service.refresh_post_rollups(self.db, post)
        add_action_log(
            self.db,
            user_id=user.id,
            action="calendar_event_updated",
            entity_type="post",
            entity_id=post.id,
            details={
                "platforms": platforms,
                "public_social_link_ids": desired_link_ids,
                "post_type": post_type,
                "end_time": end_time,
            },
        )
        await self.repository.commit()

        saved_post = await self.post_service.require_post(str(post.id), user.organization_id)
        pain_links = await self.repository.fetch_event_pain_links(saved_post.event_id)
        return self.serializer.from_post(saved_post, pain_links=pain_links)

    async def delete_event(self, event_id: str, user: User) -> None:
        """Удаляет календарное событие."""

        post = await self.post_service.require_post(event_id, user.organization_id)
        await self.publication_service.delete_publications(post)
        await self.repository.flush()
        await posts_service.refresh_post_rollups(self.db, post)
        add_action_log(
            self.db,
            user_id=user.id,
            action="calendar_event_deleted",
            entity_type="post",
            entity_id=post.id,
            details={},
        )
        await self.repository.commit()
