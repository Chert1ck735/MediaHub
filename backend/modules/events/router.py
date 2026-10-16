"""HTTP-слой событий.

По SRP этот файл не ходит в БД напрямую и не парсит файлы: он принимает запрос,
вызывает EventService и переводит доменные ошибки в HTTP-ответы.
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.events.errors import EventImportError
from backend.modules.events.schemas import (
    EventCreateRequest,
    EventImportResponse,
    EventPainLink,
    EventPainsRequest,
    EventResponse,
)
from backend.modules.events.service import EventService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/events", tags=["events"])


def _events_service(db: AsyncSession) -> EventService:
    """Фабрика держит обработчики тонкими, как в модуле auth."""
    return EventService(db)


def _bad_request(exc: EventImportError) -> HTTPException:
    """Преобразует доменную ошибку в ответ 400 для клиента."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _event_not_found() -> HTTPException:
    """Создает единый ответ 404 для всех случаев, когда событие недоступно."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Событие не найдено")


@router.get("/", response_model=list[EventResponse])
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventResponse]:
    """Возвращает список событий текущей организации."""
    logger.info(
        "Events list requested",
        extra={"user_id": str(current_user.id), "endpoint": "GET /api/events/"},
    )

    events = await _events_service(db).list_events(current_user)

    logger.info(
        "Events list built",
        extra={"user_id": str(current_user.id), "events_count": len(events)},
    )
    return [EventResponse.from_event(event) for event in events]


@router.post("/", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    payload: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    """Создает одно событие из JSON-запроса."""
    logger.info(
        "Event create requested",
        extra={
            "user_id": str(current_user.id),
            "title": payload.title,
            "event_date": payload.event_date,
        },
    )

    try:
        event = await _events_service(db).create_event(
            current_user,
            title=payload.title,
            description=payload.description,
            event_date=payload.event_date,
            location=payload.location,
            external_id=payload.external_id,
        )
    except EventImportError as exc:
        logger.warning("Event create rejected", extra={"user_id": str(current_user.id), "error": str(exc)})
        raise _bad_request(exc) from exc

    logger.info(
        "Event created",
        extra={"user_id": str(current_user.id), "event_id": str(event.id), "title": event.title},
    )
    return EventResponse.from_event(event)


@router.put("/{event_id}", response_model=EventResponse)
async def update_event(
    event_id: str,
    payload: EventCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventResponse:
    """Обновляет событие, если оно принадлежит организации пользователя."""
    logger.info(
        "Event update requested",
        extra={"user_id": str(current_user.id), "event_id": event_id, "title": payload.title},
    )

    try:
        event = await _events_service(db).update_event(
            event_id,
            current_user,
            title=payload.title,
            description=payload.description,
            event_date=payload.event_date,
            location=payload.location,
            external_id=payload.external_id,
        )
    except EventImportError as exc:
        logger.warning(
            "Event update rejected",
            extra={"user_id": str(current_user.id), "event_id": event_id, "error": str(exc)},
        )
        raise _bad_request(exc) from exc

    if not event:
        raise _event_not_found()

    logger.info(
        "Event updated",
        extra={"user_id": str(current_user.id), "event_id": str(event.id)},
    )
    return EventResponse.from_event(event)


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удаляет событие текущей организации."""
    logger.info(
        "Event delete requested",
        extra={"user_id": str(current_user.id), "event_id": event_id},
    )

    try:
        deleted = await _events_service(db).delete_event(event_id, current_user)
    except EventImportError as exc:
        logger.warning(
            "Event delete rejected",
            extra={"user_id": str(current_user.id), "event_id": event_id, "error": str(exc)},
        )
        raise _bad_request(exc) from exc

    if not deleted:
        raise _event_not_found()

    logger.info(
        "Event deleted",
        extra={"user_id": str(current_user.id), "event_id": event_id},
    )


@router.post("/import", response_model=EventImportResponse, status_code=status.HTTP_201_CREATED)
async def import_events(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventImportResponse:
    """Импортирует события из загруженного CSV/XLSX-файла."""
    logger.info(
        "Events import requested",
        extra={"user_id": str(current_user.id), "upload_filename": file.filename},
    )

    content = await file.read()
    try:
        events = await _events_service(db).import_events(
            current_user,
            filename=file.filename or "events.csv",
            content=content,
        )
    except EventImportError as exc:
        logger.warning(
            "Events import rejected",
            extra={"user_id": str(current_user.id), "upload_filename": file.filename, "error": str(exc)},
        )
        raise _bad_request(exc) from exc

    logger.info(
        "Events import completed",
        extra={
            "user_id": str(current_user.id),
            "upload_filename": file.filename,
            "imported_count": len(events),
        },
    )
    return EventImportResponse(
        imported_count=len(events),
        items=[EventResponse.from_event(event) for event in events],
    )


@router.get("/{event_id}/pains", response_model=list[EventPainLink])
async def list_event_pains(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventPainLink]:
    """Возвращает боли, привязанные к конкретному событию."""
    try:
        links = await _events_service(db).list_event_pains(event_id, current_user)
    except EventImportError as exc:
        raise _event_not_found() from exc
    if links is None:
        raise _event_not_found()
    return [EventPainLink.from_record(link) for link in links]


@router.post("/{event_id}/pains", response_model=list[EventPainLink])
async def link_event_pains(
    event_id: str,
    payload: EventPainsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[EventPainLink]:
    """Привязывает выбранные боли к событию и возвращает актуальный список связей."""
    # Идемпотентность привязки живет в репозитории через ON CONFLICT DO NOTHING.
    try:
        links = await _events_service(db).link_event_pains(
            event_id,
            current_user,
            pain_ids=payload.pain_ids,
            relation_type=payload.relation_type,
        )
    except EventImportError as exc:
        if "pain_id" in str(exc) or "бол" in str(exc).lower():
            raise _bad_request(exc) from exc
        raise _event_not_found() from exc
    if links is None:
        raise _event_not_found()
    return [EventPainLink.from_record(link) for link in links]


@router.delete("/{event_id}/pains/{pain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_event_pain(
    event_id: str,
    pain_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удаляет связь между событием и одной болью."""
    try:
        unlinked = await _events_service(db).unlink_event_pain(event_id, pain_id, current_user)
    except EventImportError as exc:
        raise _event_not_found() from exc
    if not unlinked:
        raise _event_not_found()
