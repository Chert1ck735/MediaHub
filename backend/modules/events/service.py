"""Бизнес-сценарии событий.

Сервис знает порядок действий: проверить организацию, подготовить данные,
вызвать репозитории и завершить транзакцию. SQL и парсинг файлов вынесены отдельно.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.events import Event
from backend.db.users import User
from backend.modules.events.errors import EventImportError
from backend.modules.events.importer import EventFileImporter, clean_text, parse_event_date
from backend.modules.events.repositories.event_pain_repository import EventPainRepository
from backend.modules.events.repositories.event_repository import EventRepository
from backend.modules.events.types import EventPainRecord


def event_source_label(event: Event) -> str:
    """Определяет, как показать источник события в API."""
    if event.source_id or event.imported_at or event.external_id:
        return "imported"
    return "manual"


def _is_calendar_meta(raw: str | None) -> bool:
    """Проверяет, что описание события на самом деле хранит служебные данные календаря."""
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except Exception:
        return False
    return isinstance(data, dict) and {"start_time", "end_time", "status", "platforms"}.issubset(data.keys())


def _require_org(user: User) -> uuid.UUID:
    """Достает организацию пользователя или останавливает сценарий понятной ошибкой."""
    if not user.organization_id:
        raise EventImportError("У пользователя не задана организация")
    return user.organization_id


def _parse_uuid(value: str, *, error_message: str) -> uuid.UUID:
    """Преобразует строковый id в UUID и прячет техническую ошибку парсинга."""
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError) as exc:
        raise EventImportError(error_message) from exc


class EventService:
    """Оркестрирует сценарии работы с событиями, не смешиваясь с HTTP и сырым SQL."""

    def __init__(self, db: AsyncSession):
        """Собирает зависимости сервиса вокруг одной database session."""
        self.db = db
        self.events = EventRepository(db)
        self.event_pains = EventPainRepository(db)
        self.importer = EventFileImporter()

    async def list_events(self, user: User) -> list[Event]:
        """Загружает события организации и убирает служебные календарные записи."""
        organization_id = _require_org(user)
        events = await self.events.list_by_organization(organization_id)
        return [event for event in events if not _is_calendar_meta(event.description)]

    async def create_event(
        self,
        user: User,
        *,
        title: str,
        description: str | None,
        event_date: str,
        location: str | None,
        external_id: str | None,
    ) -> Event:
        """Создает событие вручную и завершает транзакцию."""
        organization_id = _require_org(user)
        event = Event(
            title=title.strip(),
            description=clean_text(description),
            event_date=parse_event_date(event_date),
            location=clean_text(location),
            external_id=clean_text(external_id),
            imported_at=datetime.now(timezone.utc),
            organization_id=organization_id,
        )
        await self.events.add(event)
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def update_event(
        self,
        event_id: str,
        user: User,
        *,
        title: str,
        description: str | None,
        event_date: str,
        location: str | None,
        external_id: str | None,
    ) -> Event | None:
        """Обновляет событие только внутри организации пользователя."""
        organization_id = _require_org(user)
        event_uuid = _parse_uuid(event_id, error_message="Некорректный id события")
        event = await self.events.get_owned(event_uuid, organization_id)
        if not event:
            return None

        event.title = title.strip()
        event.description = clean_text(description)
        event.event_date = parse_event_date(event_date)
        event.location = clean_text(location)
        event.external_id = clean_text(external_id)

        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def delete_event(self, event_id: str, user: User) -> bool:
        """Удаляет событие организации; возвращает False, если его нет."""
        organization_id = _require_org(user)
        event_uuid = _parse_uuid(event_id, error_message="Некорректный id события")
        event = await self.events.get_owned(event_uuid, organization_id)
        if not event:
            return False

        await self.events.delete(event)
        await self.db.commit()
        return True

    async def import_events(
        self,
        user: User,
        *,
        filename: str,
        content: bytes,
    ) -> list[Event]:
        """Разбирает файл событий и сохраняет получившиеся записи в БД."""
        organization_id = _require_org(user)
        events = self.importer.parse(
            filename=filename,
            content=content,
            organization_id=organization_id,
        )
        if not events:
            return []

        self.events.add_many(events)
        await self.db.commit()
        for event in events:
            await self.db.refresh(event)
        return events

    async def get_owned_event(self, event_id: str, user: User) -> Event | None:
        """Возвращает событие только если оно принадлежит организации пользователя."""
        organization_id = _require_org(user)
        event_uuid = _parse_uuid(event_id, error_message="Некорректный id события")
        return await self.events.get_owned(event_uuid, organization_id)

    async def list_event_pains(self, event_id: str, user: User) -> list[EventPainRecord] | None:
        """Возвращает связи event-pain после проверки доступа к событию."""
        organization_id = _require_org(user)
        event = await self.get_owned_event(event_id, user)
        if not event:
            return None
        return await self.event_pains.list_links(event.id, organization_id)

    async def link_event_pains(
        self,
        event_id: str,
        user: User,
        *,
        pain_ids: list[str],
        relation_type: str = "addresses",
    ) -> list[EventPainRecord] | None:
        """Проверяет доступ, валидирует боли и создает связи с событием."""
        organization_id = _require_org(user)
        event = await self.get_owned_event(event_id, user)
        if not event:
            return None

        try:
            pain_uuids = [uuid.UUID(pain_id) for pain_id in pain_ids]
        except (ValueError, TypeError) as exc:
            raise EventImportError("Невалидный pain_id") from exc

        owned_ids = await self.event_pains.existing_pain_ids(pain_uuids, organization_id)
        if owned_ids != set(pain_uuids):
            raise EventImportError("Часть болей не найдена или из другой организации")

        # Право владения проверено выше; ниже остается только записать связь.
        normalized_relation_type = (relation_type or "addresses").strip().lower() or "addresses"
        await self.event_pains.link_many(event.id, pain_uuids, normalized_relation_type)
        await self.db.commit()
        return await self.event_pains.list_links(event.id, organization_id)

    async def unlink_event_pain(self, event_id: str, pain_id: str, user: User) -> bool:
        """Удаляет одну связь event-pain после проверки доступа к событию."""
        event = await self.get_owned_event(event_id, user)
        if not event:
            return False

        pain_uuid = _parse_uuid(pain_id, error_message="Некорректный id боли")
        await self.event_pains.unlink(event.id, pain_uuid)
        await self.db.commit()
        return True


# Функции-обертки оставлены для старых импортов и тестов.
async def list_events(db: AsyncSession, user: User) -> list[Event]:
    """Совместимость со старым API: делегирует список событий в EventService."""
    return await EventService(db).list_events(user)


async def create_event(
    db: AsyncSession,
    user: User,
    *,
    title: str,
    description: str | None,
    event_date: str,
    location: str | None,
    external_id: str | None,
) -> Event:
    """Совместимость со старым API: делегирует создание события в EventService."""
    return await EventService(db).create_event(
        user,
        title=title,
        description=description,
        event_date=event_date,
        location=location,
        external_id=external_id,
    )


async def update_event(
    db: AsyncSession,
    event_id: str,
    user: User,
    *,
    title: str,
    description: str | None,
    event_date: str,
    location: str | None,
    external_id: str | None,
) -> Event | None:
    """Совместимость со старым API: делегирует обновление события в EventService."""
    return await EventService(db).update_event(
        event_id,
        user,
        title=title,
        description=description,
        event_date=event_date,
        location=location,
        external_id=external_id,
    )


async def delete_event(db: AsyncSession, event_id: str, user: User) -> bool:
    """Совместимость со старым API: делегирует удаление события в EventService."""
    return await EventService(db).delete_event(event_id, user)


async def import_events(
    db: AsyncSession,
    user: User,
    *,
    filename: str,
    content: bytes,
) -> list[Event]:
    """Совместимость со старым API: делегирует импорт событий в EventService."""
    return await EventService(db).import_events(user, filename=filename, content=content)
