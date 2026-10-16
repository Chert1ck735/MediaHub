"""Репозиторий событий для analytics action-plan context."""

import uuid
from datetime import timezone, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import Row, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Event, EventPain, Post, User


class EventRepository:
    """SQL-доступ к событиям, связанным с болями."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def count_events_for_pain(self, pain_id: uuid.UUID) -> int:
        """Число событий, связанных с болью."""

        result = await self._db.execute(
            select(func.count(EventPain.pain_id)).where(EventPain.pain_id == pain_id)
        )
        return int(result.scalar() or 0)

    async def latest_post_at_for_pain(self, pain_id: uuid.UUID) -> datetime | None:
        """Дата последнего поста (published/scheduled) по событиям боли."""

        result = await self._db.execute(
            select(func.max(func.coalesce(Post.published_at, Post.scheduled_at)))
            .join(EventPain, EventPain.event_id == Post.event_id)
            .where(EventPain.pain_id == pain_id)
            .where(or_(Post.published_at.is_not(None), Post.scheduled_at.is_not(None)))
        )
        return result.scalar()

    async def count_events_by_pains(
        self, pain_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Число событий по каждой боли одним запросом."""

        if not pain_ids:
            return {}
        rows = await self._db.execute(
            select(EventPain.pain_id, func.count())
            .where(EventPain.pain_id.in_(pain_ids))
            .group_by(EventPain.pain_id)
        )
        return {pain_id: int(count) for pain_id, count in rows.all()}

    async def latest_post_at_by_pains(
        self, pain_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, datetime]:
        """Дата последнего поста по каждой боли одним запросом."""

        if not pain_ids:
            return {}
        rows = await self._db.execute(
            select(
                EventPain.pain_id,
                func.max(func.coalesce(Post.published_at, Post.scheduled_at)),
            )
            .join(Post, Post.event_id == EventPain.event_id)
            .where(EventPain.pain_id.in_(pain_ids))
            .where(or_(Post.published_at.is_not(None), Post.scheduled_at.is_not(None)))
            .group_by(EventPain.pain_id)
        )
        return {pain_id: dt for pain_id, dt in rows.all() if dt is not None}

    async def list_posts_for_pain(self, pain_id: uuid.UUID) -> Sequence[Row]:
        """Сырые строки постов (id, title, published_at, scheduled_at) по событиям боли."""

        result = await self._db.execute(
            select(Post.id, Post.title, Post.published_at, Post.scheduled_at)
            .join(EventPain, EventPain.event_id == Post.event_id)
            .where(EventPain.pain_id == pain_id)
            .where(Post.event_id.is_not(None))
        )
        return result.all()

    async def list_events_for_pain(
        self,
        pain_id: uuid.UUID,
        user: User,
    ) -> Sequence[Row]:
        """Сырые строки событий, привязанных к боли (без сборки DTO)."""

        result = await self._db.execute(
            select(
                Event.id,
                Event.title,
                Event.event_date,
                Event.location,
                Event.description,
                EventPain.relation_type,
            )
            .select_from(EventPain)
            .join(Event, Event.id == EventPain.event_id)
            .where(EventPain.pain_id == pain_id)
            .where(Event.organization_id == user.organization_id)
            .order_by(Event.event_date.desc())
        )
        return result.all()

    async def list_posts_for_events(
        self,
        event_ids: list[uuid.UUID],
        user: User,
    ) -> Sequence[Row]:
        """Сырые строки постов организации по списку событий."""

        if not event_ids:
            return []
        result = await self._db.execute(
            select(Post.id, Post.title, Post.event_id, Post.scheduled_at, Post.status)
            .where(Post.event_id.in_(event_ids))
            .where(Post.organization_id == user.organization_id)
            .order_by(Post.scheduled_at.desc().nulls_last(), Post.created_at.desc())
        )
        return result.all()

    async def list_upcoming_events_by_pain(
        self,
        pain_ids: list[uuid.UUID],
        *,
        days_ahead: int,
    ) -> dict[str, list[dict[str, Any]]]:
        """Возвращает ближайшие события, сгруппированные по pain_id."""

        if not pain_ids:
            return {}

        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)

        rows = await self._db.execute(
            select(
                EventPain.pain_id,
                Event.id,
                Event.title,
                Event.event_date,
                Event.location,
            )
            .select_from(EventPain)
            .join(Event, Event.id == EventPain.event_id)
            .where(EventPain.pain_id.in_(pain_ids))
            .where(Event.event_date >= now)
            .where(Event.event_date <= end)
            .order_by(Event.event_date.asc())
        )

        grouped: dict[str, list[dict[str, Any]]] = {}
        for pain_id, event_id, title, event_date, location in rows.all():
            grouped.setdefault(str(pain_id), []).append(
                {
                    "event_id": str(event_id),
                    "title": title,
                    "date": event_date.isoformat() if event_date else "",
                    "location": location,
                }
            )
        return grouped
