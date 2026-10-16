"""Гарантии схемы RBAC на реальной БД (media_test).

Проверяем ровно то, что схема ОБЕЩАЕТ обеспечить сама, без участия сервисного
слоя. Если какой-то из этих тестов падает — значит инвариант держится только на
честном слове приложения, и его обойдёт любой другой писатель (миграция, psql,
второй сервис).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from backend.db import (
    AccessGrant,
    CommunityGroup,
    CommunityGroupMember,
    Organization,
    Public,
    User,
    UserGroup,
    UserGroupMember,
)
from backend.db.enums import (
    AccessResourceType,
    AccessSubjectType,
    OrgType,
    PermissionEnum,
    UserRole,
)

# loop_scope="session" обязателен: фикстура db_session живёт в session-loop
# (asyncio_default_fixture_loop_scope в pytest.ini), и без этого маркера тест
# крутился бы в function-loop, а asyncpg падал бы с "attached to a different loop".
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
]


async def _org(session, name: str) -> Organization:
    org = Organization(name=name, type=OrgType.government)
    session.add(org)
    await session.flush()
    return org


async def _user(session, org: Organization, email: str) -> User:
    user = User(
        first_name="Иван",
        last_name="Тестов",
        email=email,
        password_hash="x",
        role=UserRole.minion,
        organization_id=org.id,
    )
    session.add(user)
    await session.flush()
    return user


async def test_email_must_be_unique(db_session):
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    await _user(db_session, org, "dup@example.ru")

    # Второго пользователя добавляем без flush внутри хелпера — иначе
    # IntegrityError вылетит раньше, чем мы войдём в pytest.raises.
    db_session.add(
        User(
            first_name="Пётр",
            last_name="Дублёв",
            email="dup@example.ru",
            password_hash="x",
            role=UserRole.minion,
            organization_id=org.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_email_must_be_lowercase(db_session):
    """CHECK не даёт записать email в верхнем регистре.

    Без него уникальность email обходится сменой регистра: Ivan@x.ru и
    ivan@x.ru — две разные строки, но один и тот же почтовый ящик.
    """
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    db_session.add(
        User(
            first_name="Иван",
            last_name="Тестов",
            email="Ivan@Example.RU",
            password_hash="x",
            role=UserRole.minion,
            organization_id=org.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_user_group_member_must_share_organization(db_session):
    """Пользователя одной организации нельзя положить в группу другой.

    Это гарантия составных FK, а не сервисного слоя.
    """
    org_a = await _org(db_session, f"a-{uuid.uuid4()}")
    org_b = await _org(db_session, f"b-{uuid.uuid4()}")

    group_a = UserGroup(organization_id=org_a.id, name="Группа A")
    db_session.add(group_a)
    user_b = await _user(db_session, org_b, f"{uuid.uuid4()}@x.ru")
    await db_session.flush()

    db_session.add(
        UserGroupMember(
            user_group_id=group_a.id,
            user_id=user_b.id,
            organization_id=org_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_user_group_member_same_organization_is_allowed(db_session):
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    group = UserGroup(organization_id=org.id, name="Своя группа")
    db_session.add(group)
    user = await _user(db_session, org, f"{uuid.uuid4()}@x.ru")
    await db_session.flush()

    db_session.add(
        UserGroupMember(
            user_group_id=group.id,
            user_id=user.id,
            organization_id=org.id,
        )
    )
    await db_session.flush()  # не должно падать


async def test_community_group_member_must_share_organization(db_session):
    """Сообщество чужой организации нельзя добавить в группу сообществ."""
    org_a = await _org(db_session, f"a-{uuid.uuid4()}")
    org_b = await _org(db_session, f"b-{uuid.uuid4()}")

    group_a = CommunityGroup(organization_id=org_a.id, name="Группа сообществ A")
    public_b = Public(organization_id=org_b.id, name=f"Паблик-{uuid.uuid4()}")
    db_session.add_all([group_a, public_b])
    await db_session.flush()

    db_session.add(
        CommunityGroupMember(
            community_group_id=group_a.id,
            public_id=public_b.id,
            organization_id=org_a.id,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_user_group_name_unique_per_organization(db_session):
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    db_session.add(UserGroup(organization_id=org.id, name="Дубль"))
    await db_session.flush()

    db_session.add(UserGroup(organization_id=org.id, name="Дубль"))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_same_group_name_allowed_in_other_organization(db_session):
    """Одноимённые группы в разных организациях — норма, а не конфликт."""
    org_a = await _org(db_session, f"a-{uuid.uuid4()}")
    org_b = await _org(db_session, f"b-{uuid.uuid4()}")

    db_session.add(UserGroup(organization_id=org_a.id, name="Модераторы"))
    db_session.add(UserGroup(organization_id=org_b.id, name="Модераторы"))
    await db_session.flush()  # не должно падать


async def test_duplicate_grant_is_rejected(db_session):
    """Один и тот же грант нельзя выдать дважды."""
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    user = await _user(db_session, org, f"{uuid.uuid4()}@x.ru")
    public = Public(organization_id=org.id, name=f"Паблик-{uuid.uuid4()}")
    db_session.add(public)
    await db_session.flush()

    def _grant() -> AccessGrant:
        return AccessGrant(
            organization_id=org.id,
            subject_type=AccessSubjectType.user,
            subject_id=user.id,
            resource_type=AccessResourceType.community,
            resource_id=public.id,
            permission=PermissionEnum.view_community,
        )

    db_session.add(_grant())
    await db_session.flush()

    db_session.add(_grant())
    with pytest.raises(IntegrityError):
        await db_session.flush()
    # Сессия после провалившегося flush аварийна — обязателен откат,
    # иначе развалится уборка фикстуры (TRUNCATE).
    await db_session.rollback()


async def test_different_permission_on_same_resource_is_allowed(db_session):
    """view_community и create_post на одно сообщество — два разных гранта."""
    org = await _org(db_session, f"org-{uuid.uuid4()}")
    user = await _user(db_session, org, f"{uuid.uuid4()}@x.ru")
    public = Public(organization_id=org.id, name=f"Паблик-{uuid.uuid4()}")
    db_session.add(public)
    await db_session.flush()

    for permission in (PermissionEnum.view_community, PermissionEnum.create_post):
        db_session.add(
            AccessGrant(
                organization_id=org.id,
                subject_type=AccessSubjectType.user,
                subject_id=user.id,
                resource_type=AccessResourceType.community,
                resource_id=public.id,
                permission=permission,
            )
        )
    await db_session.flush()  # не должно падать


async def test_deleting_group_cascades_membership(db_session):
    """Удаление группы уносит членство, а не оставляет висячие строки."""
    from sqlalchemy import func, select

    org = await _org(db_session, f"org-{uuid.uuid4()}")
    group = UserGroup(organization_id=org.id, name="Временная")
    db_session.add(group)
    user = await _user(db_session, org, f"{uuid.uuid4()}@x.ru")
    await db_session.flush()

    db_session.add(
        UserGroupMember(
            user_group_id=group.id, user_id=user.id, organization_id=org.id
        )
    )
    await db_session.flush()

    await db_session.delete(group)
    await db_session.flush()

    left = await db_session.scalar(
        select(func.count())
        .select_from(UserGroupMember)
        .where(UserGroupMember.user_group_id == group.id)
    )
    assert left == 0
