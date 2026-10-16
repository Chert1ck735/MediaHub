"""Новые правила прав: просмотр по умолчанию, организации — только суперадмину."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db import Event, Organization, Post, Public, User
from backend.db.enums import OrgType, PermissionEnum, UserRole, UserStatus
from backend.modules.organization.services.authorization_service import (
    AuthorizationError,
    AuthorizationService,
)
from backend.modules.organization.services.organization_service import OrganizationService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _org(session, name: str = "Орг") -> Organization:
    org = Organization(name=f"{name}-{uuid.uuid4()}", type=OrgType.government)
    session.add(org)
    await session.flush()
    return org


async def _user(session, org: Organization, role: UserRole) -> User:
    user = User(
        first_name="Имя",
        last_name="Фамилия",
        email=f"{uuid.uuid4()}@x.ru",
        password_hash="x",
        role=role,
        status=UserStatus.active,
        organization_id=org.id,
    )
    session.add(user)
    await session.flush()
    return user


async def _public(session, org: Organization) -> Public:
    public = Public(organization_id=org.id, name=f"Паблик-{uuid.uuid4()}")
    session.add(public)
    await session.flush()
    return public


# ── просмотр по умолчанию ───────────────────────────────────────────────────

async def test_minion_sees_all_communities_without_any_grant(db_session):
    """Сотрудник видит ВСЕ сообщества своей организации без единого гранта.

    Человек не может работать с тем, чего не видит; заводить грант на просмотр
    каждому на каждое сообщество — бессмысленная бухгалтерия.
    """
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public_a = await _public(db_session, org)
    public_b = await _public(db_session, org)
    await db_session.commit()

    authz = AuthorizationService(db_session)
    for public in (public_a, public_b):
        assert await authz.has_permission(
            minion, public.id, PermissionEnum.view_community
        )

    # Список не фильтруется: None = «все сообщества организации».
    assert await authz.list_accessible_community_ids(
        minion, PermissionEnum.view_community
    ) is None


async def test_default_view_does_not_grant_publishing(db_session):
    """Просмотр открыт всем — публикация по-прежнему только по гранту."""
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)
    await db_session.commit()

    authz = AuthorizationService(db_session)
    assert await authz.has_permission(minion, public.id, PermissionEnum.view_community)
    assert not await authz.has_permission(minion, public.id, PermissionEnum.create_post)

    with pytest.raises(AuthorizationError) as exc:
        await authz.require_permission(minion, public.id, PermissionEnum.create_post)
    assert exc.value.status_code == 403


async def test_default_view_does_not_cross_organizations(db_session):
    """Просмотр по умолчанию — только СВОЕЙ организации. Изоляция сохраняется."""
    org_a = await _org(db_session, "A")
    org_b = await _org(db_session, "B")
    minion_a = await _user(db_session, org_a, UserRole.minion)
    public_b = await _public(db_session, org_b)
    await db_session.commit()

    assert not await AuthorizationService(db_session).has_permission(
        minion_a, public_b.id, PermissionEnum.view_community
    )


# ── организации: только суперадмин ──────────────────────────────────────────

async def test_admin_cannot_change_organization_type(db_session):
    """Тип организации — за суперадмином. Название править можно."""
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    service = OrganizationService(db_session)

    renamed = await service.update(admin, org.id, name="Новое имя")
    assert renamed.name == "Новое имя"

    with pytest.raises(AuthorizationError):
        await service.update(admin, org.id, org_type=OrgType.business)


async def test_setting_same_type_is_not_a_change(db_session):
    """Передать тот же тип — не изменение, отказывать не за что."""
    org = await _org(db_session)  # government
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    # Не должно бросать: тип фактически не меняется.
    await OrganizationService(db_session).update(
        admin, org.id, name="Ок", org_type=OrgType.government
    )


async def test_admin_cannot_delete_organization(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    with pytest.raises(AuthorizationError) as exc:
        await OrganizationService(db_session).delete(admin, org.id)
    assert exc.value.status_code == 403


async def test_superadmin_deletes_organization(db_session):
    home = await _org(db_session, "Своя")
    target = await _org(db_session, "Под снос")
    root = await _user(db_session, home, UserRole.superadmin)
    await _user(db_session, target, UserRole.admin)
    await _public(db_session, target)
    await db_session.commit()

    await OrganizationService(db_session).delete(root, target.id)

    gone = await db_session.scalar(
        select(Organization.id).where(Organization.id == target.id)
    )
    assert gone is None


async def test_superadmin_deletes_organization_with_posts_and_events(db_session):
    home = await _org(db_session, "Своя")
    target = await _org(db_session, "Под снос")
    root = await _user(db_session, home, UserRole.superadmin)
    author = await _user(db_session, target, UserRole.admin)
    event = Event(
        title="Событие",
        event_date=datetime.now(timezone.utc),
        imported_at=datetime.now(timezone.utc),
        organization_id=target.id,
    )
    post = Post(
        title="Пост",
        text_final="Текст",
        author_id=author.id,
        organization_id=target.id,
    )
    db_session.add_all([event, post])
    await db_session.commit()

    await OrganizationService(db_session).delete(root, target.id)

    assert await db_session.scalar(select(Post.id).where(Post.id == post.id)) is None
    assert await db_session.scalar(select(Event.id).where(Event.id == event.id)) is None


async def test_superadmin_cannot_delete_own_organization(db_session):
    """Иначе суперадмин отрежет сам себя."""
    org = await _org(db_session)
    root = await _user(db_session, org, UserRole.superadmin)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await OrganizationService(db_session).delete(root, org.id)
    assert exc.value.status_code == 409
