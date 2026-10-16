from datetime import datetime, timezone

from backend.db import Publication


def schedule_dt(date: str, start_time: str) -> datetime:
    """Собирает timezone-aware datetime из даты и времени."""

    parsed = datetime.fromisoformat(f"{date}T{start_time}:00")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def effective_publication_dt(publication: Publication) -> datetime:
    """Возвращает дату, по которой публикация отображается в календаре."""

    if publication.status.value == "scheduled" and publication.scheduled_at:
        return publication.scheduled_at
    if publication.published_at:
        return publication.published_at
    if publication.scheduled_at:
        return publication.scheduled_at
    return publication.created_at


def unique_ids(values: list[str] | None) -> list[str]:
    """Удаляет дубликаты id с сохранением порядка."""

    return list(dict.fromkeys(values or []))
