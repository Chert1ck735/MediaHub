"""FastAPI-роутер автопарсера: статус и ручной прогон (для проверки)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.config import settings
from backend.app.runtime_settings import (
    get_autoparse_interval_hours,
    set_autoparse_interval_hours,
)
from backend.db.database import async_session_maker, get_db
from backend.db.enums import UserRole
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.autoparse.repository import AutoParseRepository
from backend.modules.autoparse.schemas import (
    AutoParseConfig,
    AutoParseConfigUpdate,
    AutoParseLinkResult,
    AutoParseLinkStatus,
    AutoParseRunResponse,
    AutoParseStatusResponse,
)
from backend.modules.autoparse.service import AutoParseService
from backend.modules.jobs.models import JobKind
from backend.modules.jobs.store import ProgressReporter, create_job, run_job_in_background
from backend.modules.vk.services.subscriber_refresh_service import VkSubscriberRefreshService

router = APIRouter(prefix="/api/autoparse", tags=["autoparse"])


def _require_org(user: User) -> UUID:
    if user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="У пользователя не задана организация",
        )
    return user.organization_id


def _require_admin(user: User) -> None:
    if user.role not in (UserRole.admin, UserRole.superadmin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ручной прогон автопарсера доступен только администратору",
        )


def _require_superadmin(user: User) -> None:
    if user.role != UserRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Обновление подписчиков доступно только суперадминистратору",
        )


def _config(interval_hours: int) -> AutoParseConfig:
    return AutoParseConfig(
        enabled=settings.AUTOPARSE_ENABLED,
        interval_hours=interval_hours,
        lookback_days=settings.AUTOPARSE_LOOKBACK_DAYS,
        check_interval_seconds=settings.AUTOPARSE_CHECK_INTERVAL_SECONDS,
        max_posts=settings.AUTOPARSE_MAX_POSTS,
    )


@router.get("/config", response_model=AutoParseConfig)
async def autoparse_config(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutoParseConfig:
    """Текущие настройки автопарсера (период — из БД)."""

    interval_hours = await get_autoparse_interval_hours(db)
    return _config(interval_hours)


@router.put("/config", response_model=AutoParseConfig)
async def autoparse_config_update(
    payload: AutoParseConfigUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutoParseConfig:
    """Меняет период автопарсера. Глобальная настройка — только суперадмин."""

    if user.role != UserRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Период автопарсера меняет только суперадминистратор",
        )
    interval_hours = await set_autoparse_interval_hours(db, payload.interval_hours)
    await db.commit()
    return _config(interval_hours)


@router.get("/status", response_model=AutoParseStatusResponse)
async def autoparse_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AutoParseStatusResponse:
    """Ссылки организации под автопарсером и когда их проверяли в последний раз."""

    org_id = _require_org(user)
    now = datetime.now(timezone.utc)
    interval_hours = await get_autoparse_interval_hours(db)
    cutoff = now - timedelta(hours=interval_hours)

    repo = AutoParseRepository(db)
    links = await repo.list_links(
        now=now,
        interval_hours=interval_hours,
        only_due=False,
        organization_id=org_id,
    )

    return AutoParseStatusResponse(
        config=_config(interval_hours),
        links=[
            AutoParseLinkStatus(
                link_id=str(link.link_id),
                network=link.network,
                url=link.url,
                public_id=str(link.public_id),
                public_name=link.public_name,
                last_autoparse_at=link.last_autoparse_at,
                is_due=link.last_autoparse_at is None or link.last_autoparse_at < cutoff,
            )
            for link in links
        ],
    )


@router.post("/run", response_model=AutoParseRunResponse)
async def autoparse_run(
    only_due: bool = Query(
        False,
        description="true — только созревшие по периоду; false — прогнать все ссылки орг-ии сейчас",
    ),
    link_id: UUID | None = Query(None, description="Прогнать одну конкретную ссылку"),
    user: User = Depends(get_current_user),
) -> AutoParseRunResponse:
    """Прогоняет автопарсер по организации прямо сейчас и возвращает разбор по
    каждой ссылке (проверено / есть дифф / спарсено N комментов / пропущено).

    Синхронный: ходит в VK/OK, поэтому на большой организации может занять
    десятки секунд. Для точечной проверки укажите ``link_id``.
    """

    _require_admin(user)
    org_id = _require_org(user)

    service = AutoParseService(async_session_maker)
    result = await service.run_once(
        only_due=only_due,
        organization_id=org_id,
        link_id=link_id,
    )

    return AutoParseRunResponse(
        started_at=result.started_at,
        finished_at=result.finished_at,
        lookback_days=result.lookback_days,
        links_total=result.links_total,
        links_checked=result.links_checked,
        links_parsed=result.links_parsed,
        comments_imported=result.comments_imported,
        links=[AutoParseLinkResult(**link.to_dict()) for link in result.links],
    )


@router.post("/subscribers/refresh")
async def refresh_vk_subscribers(
    user: User = Depends(get_current_user),
) -> dict:
    """Запускает обновление числа подписчиков по всем активным ссылкам VK."""

    _require_superadmin(user)
    job = await create_job(
        JobKind.vk_subscribers_refresh,
        message="Подготовка обновления подписчиков VK…",
    )

    async def runner(progress: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            stats = await VkSubscriberRefreshService(session).refresh_all(progress=progress)
            return stats.to_dict()

    run_job_in_background(job, runner)
    return {"job_id": job.id}
