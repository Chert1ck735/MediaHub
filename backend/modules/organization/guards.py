"""Проверки прав для УЖЕ существующих ручек (аналитика, публикации).

Живёт отдельно от ``services/``, потому что это точка интеграции: сюда ходят
чужие модули (publications, analytics, vk, ok), и импортировать ради этого их
внутренности сервисного слоя незачем.

Смысл: запрос в обход UI обязан получить 403, а не пустой список и не 200.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import PermissionEnum
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.users import User
from backend.modules.organization.services.authorization_service import (
    AuthorizationError,
    AuthorizationService,
)


async def community_id_for_link(
    db: AsyncSession,
    public_social_link_id: uuid.UUID | str,
) -> uuid.UUID:
    """Сообщество (``publics.id``), которому принадлежит площадка соцсети.

    Публикации и аналитика оперируют ``public_social_link_id``, а права выданы
    на сообщество — здесь мостик между ними.
    """
    try:
        link_uuid = uuid.UUID(str(public_social_link_id))
    except (ValueError, AttributeError, TypeError):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Некорректный идентификатор площадки"
        )

    public_id = await db.scalar(
        select(PublicSocialLink.public_id).where(PublicSocialLink.id == link_uuid)
    )
    if public_id is None:
        # 404, а не 403: площадки нет вообще — скрывать нечего.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Площадка не найдена")
    return public_id


async def require_link_permission(
    db: AsyncSession,
    actor: User,
    public_social_link_id: uuid.UUID | str,
    permission: PermissionEnum,
) -> uuid.UUID:
    """403, если у актора нет права на сообщество этой площадки."""
    community_id = await community_id_for_link(db, public_social_link_id)
    await AuthorizationService(db).require_permission(actor, community_id, permission)
    return community_id


async def require_community_permission(
    db: AsyncSession,
    actor: User,
    community_id: uuid.UUID,
    permission: PermissionEnum,
) -> None:
    await AuthorizationService(db).require_permission(actor, community_id, permission)


async def accessible_community_ids(
    db: AsyncSession,
    actor: User,
    permission: PermissionEnum = PermissionEnum.view_community,
) -> list[uuid.UUID] | None:
    """Сообщества, доступные актору. ``None`` = все (админ/суперадмин)."""
    return await AuthorizationService(db).list_accessible_community_ids(actor, permission)


async def visible_publics(db: AsyncSession, actor: User) -> list[Public]:
    """Сообщества организации, которые актору РАЗРЕШЕНО видеть.

    Миньону отдаём только выданные ему: список сообществ — тоже данные, и
    показывать чужие названия «просто для галочки» не нужно.
    """
    stmt = select(Public).where(Public.organization_id == actor.organization_id)

    ids = await accessible_community_ids(db, actor)
    if ids is not None:
        if not ids:
            return []
        stmt = stmt.where(Public.id.in_(ids))

    stmt = stmt.order_by(Public.name.asc())
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "AuthorizationError",
    "accessible_community_ids",
    "community_id_for_link",
    "require_community_permission",
    "require_link_permission",
    "visible_publics",
]
