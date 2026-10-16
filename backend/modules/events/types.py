from dataclasses import dataclass


@dataclass(frozen=True)
class EventPainRecord:
    """Внутренняя модель чтения связи события и боли, без привязки к FastAPI/Pydantic."""

    pain_id: str
    pain_title: str
    pain_category: str | None
    relation_type: str
