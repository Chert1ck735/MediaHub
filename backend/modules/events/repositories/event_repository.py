"""Репозиторий событий.

Здесь живут только SQL-операции с таблицей events.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.events import Event


class EventRepository:
    """Отвечает только за чтение и запись Event в БД."""

    def __init__(self, db: AsyncSession):
        """Сохраняет session, через которую выполняются запросы к events."""
        self.db = db

    async def list_by_organization(self, organization_id: uuid.UUID) -> list[Event]:
        """Возвращает все события организации в порядке от новых к старым."""
        result = await self.db.execute(
            select(Event)
            .where(Event.organization_id == organization_id)
            .order_by(Event.event_date.desc(), Event.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_owned(self, event_id: uuid.UUID, organization_id: uuid.UUID) -> Event | None:
        """Ищет событие по id, сразу ограничивая поиск организацией."""
        result = await self.db.execute(
            select(Event).where(
                Event.id == event_id,
                Event.organization_id == organization_id,
            )
        )
        return result.scalar_one_or_none()

    async def add(self, event: Event) -> Event:
        """Добавляет одно событие в текущую транзакцию."""
        self.db.add(event)
        return event

    def add_many(self, events: list[Event]) -> None:
        """Добавляет пачку событий в текущую транзакцию."""
        self.db.add_all(events)

    async def delete(self, event: Event) -> None:
        """Помечает событие на удаление в текущей транзакции."""
        await self.db.delete(event)
