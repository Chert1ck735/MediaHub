from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from uuid import UUID

from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.calendar.services.event_service import CalendarEventService
from backend.modules.calendar.utils.errors import CalendarExternalServiceError, CalendarValidationError, \
    CalendarNotFoundError
from backend.modules.calendar.schemas import EventCreateRequest, EventResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def get_calendar_service(db: AsyncSession = Depends(get_db)) -> CalendarEventService:
    """Создает сервис календаря для FastAPI dependency injection."""

    return CalendarEventService(db)


def _to_http_error(exc: Exception) -> HTTPException:
    """Преобразует доменную ошибку календаря в HTTPException."""

    if isinstance(exc, CalendarNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, CalendarValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, CalendarExternalServiceError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Ошибка календаря")


@router.get("/", response_model=list[EventResponse])
async def list_events(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    per_day: int | None = Query(default=None, ge=1, le=20),
    public_social_link_ids: str | None = None,
    timezone_name: str = "UTC",
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    calendar_service: CalendarEventService = Depends(get_calendar_service),
) -> list[dict]:
    """Возвращает календарные события за показываемый период.

    Без окна отдаются последние публикации: вся история организации — это
    десятки тысяч записей, и одним ответом она не помещается.
    """

    try:
        ZoneInfo(timezone_name)
        link_ids = [str(UUID(one.strip())) for one in (public_social_link_ids or "").split(",") if one.strip()]
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Некорректный часовой пояс или идентификатор паблика") from exc
    # Legacy callers may send naive datetimes; their documented meaning is UTC.
    if date_from and date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    if date_to and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="Начало периода должно предшествовать концу")

    logger.info(
        "Получение списка событий | user_id=%s | окно=%s..%s",
        current_user.id, date_from, date_to,
    )

    try:
        events = await calendar_service.list_events(
            current_user,
            date_from=date_from,
            date_to=date_to,
            per_day=per_day,
            link_ids=link_ids or None,
            timezone_name=timezone_name,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        logger.exception("Ошибка получения списка событий | user_id=%s", current_user.id)
        raise _to_http_error(exc) from exc

    logger.info("Список событий получен | user_id=%s | count=%s", current_user.id, len(events))
    return events


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: UUID,
    current_user: User = Depends(get_current_user),
    calendar_service: CalendarEventService = Depends(get_calendar_service),
) -> dict:
    """Full post for editing, including every publication target."""
    try:
        post = await calendar_service.post_service.require_post(str(event_id), current_user.organization_id)
        pains = await calendar_service.repository.fetch_event_pain_links(post.event_id)
        return calendar_service.serializer.from_post(post, pain_links=pains)
    except Exception as exc:
        raise _to_http_error(exc) from exc


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    calendar_service: CalendarEventService = Depends(get_calendar_service),
) -> dict:
    """Создает календарное событие."""

    logger.info(
        "Создание события | user_id=%s | title=%s | date=%s",
        current_user.id,
        payload.title,
        payload.date,
    )

    try:
        event = await calendar_service.create_event(
            current_user,
            title=payload.title,
            date=payload.date,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            ev_status=payload.status,
            platforms=payload.platforms,
            public_social_link_ids=payload.public_social_link_ids,
            draft=payload.draft,
            tone=payload.tone,
            post_type=payload.post_type,
            post_id=payload.post_id,
            info_event_id=payload.info_event_id,
        )
    except Exception as exc:
        logger.exception("Ошибка создания события | user_id=%s", current_user.id)
        raise _to_http_error(exc) from exc

    logger.info("Событие создано | event_id=%s | user_id=%s", event.get("id"), current_user.id)
    return event


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    payload: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    calendar_service: CalendarEventService = Depends(get_calendar_service),
) -> dict:
    """Обновляет календарное событие."""

    logger.info("Обновление события | event_id=%s | user_id=%s", event_id, current_user.id)

    try:
        event = await calendar_service.update_event(
            event_id,
            current_user,
            title=payload.title,
            date=payload.date,
            description=payload.description,
            start_time=payload.start_time,
            end_time=payload.end_time,
            ev_status=payload.status,
            platforms=payload.platforms,
            public_social_link_ids=payload.public_social_link_ids,
            draft=payload.draft,
            tone=payload.tone,
            post_type=payload.post_type,
            info_event_id=payload.info_event_id,
        )
    except Exception as exc:
        logger.exception("Ошибка обновления события | event_id=%s", event_id)
        raise _to_http_error(exc) from exc

    logger.info("Событие обновлено | event_id=%s | user_id=%s", event_id, current_user.id)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    calendar_service: CalendarEventService = Depends(get_calendar_service),
) -> None:
    """Удаляет календарное событие."""

    logger.info("Удаление события | event_id=%s | user_id=%s", event_id, current_user.id)

    try:
        await calendar_service.delete_event(event_id, current_user)
    except Exception as exc:
        logger.exception("Ошибка удаления события | event_id=%s", event_id)
        raise _to_http_error(exc) from exc

    logger.info("Событие удалено | event_id=%s | user_id=%s", event_id, current_user.id)
