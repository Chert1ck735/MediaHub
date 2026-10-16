"""Pydantic-схемы HTTP-контракта events.

Схемы отделены от router, чтобы HTTP-слой не разрастался DTO-классами.
"""

from pydantic import BaseModel, Field

from backend.db.events import Event
from backend.modules.events.types import EventPainRecord


class EventResponse(BaseModel):
    id: str
    title: str
    description: str | None
    event_date: str
    location: str | None
    source: str
    external_id: str | None
    created_at: str

    @classmethod
    def from_event(cls, event: Event) -> "EventResponse":
        """Преобразует ORM-событие в API-ответ."""
        from backend.modules.events.service import event_source_label

        return cls(
            id=str(event.id),
            title=event.title,
            description=event.description,
            event_date=event.event_date.isoformat(),
            location=event.location,
            source=event_source_label(event),
            external_id=event.external_id,
            created_at=event.created_at.isoformat(),
        )


class EventCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=10_000)
    event_date: str = Field(..., max_length=64)
    location: str | None = Field(None, max_length=255)
    external_id: str | None = Field(None, max_length=255)


class EventImportResponse(BaseModel):
    imported_count: int
    items: list[EventResponse]


class EventPainLink(BaseModel):
    pain_id: str
    pain_title: str
    pain_category: str | None = None
    relation_type: str = "addresses"

    @classmethod
    def from_record(cls, record: EventPainRecord) -> "EventPainLink":
        """Преобразует внутреннюю модель связи в API-ответ."""
        return cls(
            pain_id=record.pain_id,
            pain_title=record.pain_title,
            pain_category=record.pain_category,
            relation_type=record.relation_type,
        )


class EventPainsRequest(BaseModel):
    # Сервис ожидает небольшую ручную подборку болей, а не массовую выгрузку UUID.
    pain_ids: list[str] = Field(..., min_length=1, max_length=50)
    relation_type: str = Field("addresses", max_length=32)
