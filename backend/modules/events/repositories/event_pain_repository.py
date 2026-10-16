"""Репозиторий связей event-pain.

Здесь сосредоточены запросы к мосту event_pains и проверка владения pain.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.event_pains import EventPain
from backend.db.pains import Pain
from backend.modules.events.types import EventPainRecord


class EventPainRepository:
    """Отвечает только за SQL вокруг связей события и болей."""

    def __init__(self, db: AsyncSession):
        """Сохраняет session для запросов к event_pains и pains."""
        self.db = db

    async def list_links(self, event_id: uuid.UUID, organization_id: uuid.UUID) -> list[EventPainRecord]:
        """Возвращает боли события, доступные внутри указанной организации."""
        rows = await self.db.execute(
            select(EventPain.pain_id, EventPain.relation_type, Pain.title, Pain.category)
            .select_from(EventPain)
            .join(Pain, Pain.id == EventPain.pain_id)
            .where(EventPain.event_id == event_id)
            .where(Pain.organization_id == organization_id)
            .order_by(Pain.mentions_count.desc())
        )
        return [
            EventPainRecord(
                pain_id=str(pid),
                pain_title=title,
                pain_category=cat,
                relation_type=rt or "addresses",
            )
            for pid, rt, title, cat in rows.all()
        ]

    async def existing_pain_ids(
        self,
        pain_ids: list[uuid.UUID],
        organization_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        """Проверяет, какие pain_id реально принадлежат организации."""
        if not pain_ids:
            return set()
        rows = await self.db.execute(
            select(Pain.id).where(
                Pain.id.in_(pain_ids),
                Pain.organization_id == organization_id,
            )
        )
        return {row[0] for row in rows.all()}

    async def link_many(
        self,
        event_id: uuid.UUID,
        pain_ids: list[uuid.UUID],
        relation_type: str,
    ) -> None:
        """Создает связи event-pain, не падая при повторной привязке."""
        if not pain_ids:
            return

        rows = [
            {"event_id": event_id, "pain_id": pain_id, "relation_type": relation_type}
            for pain_id in pain_ids
        ]
        stmt = pg_insert(EventPain).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["event_id", "pain_id"])
        await self.db.execute(stmt)

    async def unlink(self, event_id: uuid.UUID, pain_id: uuid.UUID) -> None:
        """Удаляет одну связь event-pain из таблицы-моста."""
        await self.db.execute(
            delete(EventPain).where(
                EventPain.event_id == event_id,
                EventPain.pain_id == pain_id,
            )
        )
