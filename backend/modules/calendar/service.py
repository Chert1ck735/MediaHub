"""Compatibility API календаря.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from backend.db.users import User
from backend.modules.calendar.services.event_service import CalendarEventService


async def list_events(db: AsyncSession, user: User) -> list[dict]:
    """Совместимость: возвращает список календарных событий."""

    return await CalendarEventService(db).list_events(user)


async def create_event(
    db: AsyncSession,
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
    """Совместимость: создает календарное событие."""

    return await CalendarEventService(db).create_event(
        user,
        title=title,
        date=date,
        description=description,
        start_time=start_time,
        end_time=end_time,
        ev_status=ev_status,
        platforms=platforms,
        public_social_link_ids=public_social_link_ids,
        draft=draft,
        tone=tone,
        post_type=post_type,
        post_id=post_id,
        info_event_id=info_event_id,
    )


async def update_event(
    db: AsyncSession,
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
    """Совместимость: обновляет календарное событие."""

    return await CalendarEventService(db).update_event(
        event_id,
        user,
        title=title,
        date=date,
        description=description,
        start_time=start_time,
        end_time=end_time,
        ev_status=ev_status,
        platforms=platforms,
        public_social_link_ids=public_social_link_ids,
        draft=draft,
        tone=tone,
        post_type=post_type,
        info_event_id=info_event_id,
    )


async def delete_event(db: AsyncSession, event_id: str, user: User) -> None:
    """Совместимость: удаляет календарное событие."""

    await CalendarEventService(db).delete_event(event_id, user)
