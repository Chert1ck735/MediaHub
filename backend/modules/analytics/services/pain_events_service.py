"""События и посты, связанные с болью."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.event_repository import EventRepository
from backend.modules.analytics.repositories.pain_repository import PainRepository
from backend.modules.analytics.schemas import PainEventPostRef, PainEventLink


class PainEventsService:
    """Возвращает события и посты, связанные с pain."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        pain_repository: PainRepository | None = None,
        event_repository: EventRepository | None = None,
    ) -> None:
        self._db = db
        self._pain_repository = pain_repository or PainRepository(db)
        self._event_repository = event_repository or EventRepository(db)

    async def list_events(self, user: User, pain_id: str) -> list[PainEventLink]:
        """Возвращает события, привязанные к боли."""

        if await self._pain_repository.get_by_id(pain_id, user) is None:
            raise ValueError("Боль не найдена")

        pain_uuid = uuid.UUID(pain_id)
        events = await self._event_repository.list_events_for_pain(pain_uuid, user)

        event_ids = [event_id for event_id, *_ in events]
        posts_by_event: dict = {}
        for post_id, title, event_id, scheduled_at, status in await self._event_repository.list_posts_for_events(
            event_ids, user
        ):
            posts_by_event.setdefault(event_id, []).append(
                PainEventPostRef(
                    post_id=str(post_id),
                    title=title or "(без названия)",
                    scheduled_at=scheduled_at.isoformat() if scheduled_at else None,
                    status=status.value if hasattr(status, "value") else str(status),
                )
            )
        return [
            PainEventLink(
                event_id=str(event_id),
                title=title,
                event_date=event_date.isoformat() if event_date else "",
                location=location,
                description=description,
                relation_type=relation_type or "addresses",
                posts=posts_by_event.get(event_id, []),
            )
            for event_id, title, event_date, location, description, relation_type in events
        ]
