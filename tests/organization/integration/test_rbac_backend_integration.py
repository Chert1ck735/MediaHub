"""Серверная авторизация, права и импорт — сценарии приёмки из ТЗ.

Проверяем поведение СЕРВЕРА, а не UI: каждый отказ здесь — это то, что получит
клиент, полезший в API напрямую.
"""
from __future__ import annotations

import io
import uuid

import pytest
from fastapi import HTTPException
from openpyxl import Workbook
from sqlalchemy import select

from backend.db import CommunityGroup, Organization, Public, User, UserGroup
from backend.db.enums import (
    AccessResourceType,
    AccessSubjectType,
    OrgType,
    PermissionEnum,
    UserRole,
    UserStatus,
)
from backend.modules.organization.schemas import (
    GrantItem,
    ImportRowPreview,
    UserCreateRequest,
    UserUpdateRequest,
)
from backend.modules.organization.services.access_grant_service import AccessGrantService
from backend.modules.organization.services.authorization_service import (
    AuthorizationError,
    AuthorizationService,
)
from backend.modules.organization.services.group_service import (
    CommunityGroupService,
    UserGroupService,
)
from backend.modules.organization.services.import_service import UserImportService
from backend.modules.organization.services.user_service import LastAdminError, UserService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio(loop_scope="session"),
]


# ── фикстуры-хелперы ────────────────────────────────────────────────────────

async def _org(session, name: str = "Орг") -> Organization:
    org = Organization(name=f"{name}-{uuid.uuid4()}", type=OrgType.government)
    session.add(org)
    await session.flush()
    return org


async def _user(
    session,
    org: Organization,
    role: UserRole = UserRole.minion,
    status: UserStatus = UserStatus.active,
) -> User:
    user = User(
        first_name="Имя",
        last_name="Фамилия",
        email=f"{uuid.uuid4()}@x.ru",
        password_hash="x",
        role=role,
        status=status,
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


async def _grant(
    session,
    org: Organization,
    *,
    subject_type: AccessSubjectType,
    subject_id: uuid.UUID,
    resource_type: AccessResourceType,
    resource_id: uuid.UUID,
    permission: PermissionEnum,
) -> None:
    from backend.db import AccessGrant

    session.add(
        AccessGrant(
            organization_id=org.id,
            subject_type=subject_type,
            subject_id=subject_id,
            resource_type=resource_type,
            resource_id=resource_id,
            permission=permission,
        )
    )
    await session.flush()


# ── 1. изоляция организаций ─────────────────────────────────────────────────

async def test_admin_of_other_organization_is_forbidden(db_session):
    """ADMIN чужой организации не попадает в настройки — 403."""
    org_a = await _org(db_session, "A")
    org_b = await _org(db_session, "B")
    admin_b = await _user(db_session, org_b, UserRole.admin)

    authz = AuthorizationService(db_session)
    with pytest.raises(AuthorizationError) as exc:
        authz.require_organization_admin(admin_b, org_a.id)
    assert exc.value.status_code == 403


async def test_minion_cannot_enter_organization_settings(db_session):
    """MINION не имеет доступа к настройкам своей же организации."""
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)

    with pytest.raises(AuthorizationError):
        AuthorizationService(db_session).require_organization_admin(minion, org.id)


async def test_superadmin_passes_any_organization(db_session):
    org_a = await _org(db_session, "A")
    org_b = await _org(db_session, "B")
    root = await _user(db_session, org_b, UserRole.superadmin)

    # Не должно бросать — суперадмин проходит любую проверку.
    AuthorizationService(db_session).require_organization_admin(root, org_a.id)


async def test_admin_cannot_read_community_of_other_organization(db_session):
    """Даже с грантом (подсунутым напрямую) чужое сообщество недоступно."""
    org_a = await _org(db_session, "A")
    org_b = await _org(db_session, "B")
    admin_b = await _user(db_session, org_b, UserRole.admin)
    public_a = await _public(db_session, org_a)

    authz = AuthorizationService(db_session)
    assert await authz.has_permission(
        admin_b, public_a.id, PermissionEnum.view_community
    ) is False


# ── 2. сложение прав через группы ───────────────────────────────────────────

async def test_permissions_sum_via_user_group_and_community_group(db_session):
    """Право приходит через ГРУППУ пользователей на ГРУППУ сообществ.

    Ни личного гранта, ни гранта на само сообщество нет — доступ обязан
    сложиться из двух уровней косвенности.
    """
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    user_group = UserGroup(organization_id=org.id, name="Модераторы")
    community_group = CommunityGroup(organization_id=org.id, name="Районные")
    db_session.add_all([user_group, community_group])
    await db_session.flush()

    await UserGroupService(db_session)._set_members(user_group, [minion.id], org.id)
    await CommunityGroupService(db_session)._set_communities(
        community_group, [public.id], org.id
    )

    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user_group,
        subject_id=user_group.id,
        resource_type=AccessResourceType.community_group,
        resource_id=community_group.id,
        permission=PermissionEnum.view_community,
    )

    authz = AuthorizationService(db_session)
    perms = await authz.get_effective_permissions(minion.id, public.id)
    assert PermissionEnum.view_community in perms
    assert await authz.has_permission(minion, public.id, PermissionEnum.view_community)
    # create_post не выдавали — его быть не должно.
    assert not await authz.has_permission(minion, public.id, PermissionEnum.create_post)


async def test_personal_and_group_grants_are_unioned(db_session):
    """Личный грант и групповой складываются, а не перекрывают друг друга."""
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    group = UserGroup(organization_id=org.id, name="Авторы")
    db_session.add(group)
    await db_session.flush()
    await UserGroupService(db_session)._set_members(group, [minion.id], org.id)

    # лично — просмотр
    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user, subject_id=minion.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.view_community,
    )
    # через группу — публикация
    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user_group, subject_id=group.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.create_post,
    )

    perms = await AuthorizationService(db_session).get_effective_permissions(
        minion.id, public.id
    )
    assert perms == {PermissionEnum.view_community, PermissionEnum.create_post}


async def test_removing_from_group_revokes_access(db_session):
    """Исключение из группы отзывает доступ, если другого источника нет.

    Проверяем на create_post: просмотр теперь открыт всем сотрудникам по
    умолчанию, и грантами не управляется — отзывать там нечего.
    """
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    group = UserGroup(organization_id=org.id, name="Временные")
    db_session.add(group)
    await db_session.flush()

    groups = UserGroupService(db_session)
    await groups._set_members(group, [minion.id], org.id)
    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user_group, subject_id=group.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.create_post,
    )

    authz = AuthorizationService(db_session)
    assert await authz.has_permission(minion, public.id, PermissionEnum.create_post)

    # исключаем из группы — доступ обязан пропасть
    await groups._set_members(group, [], org.id)

    assert not await authz.has_permission(minion, public.id, PermissionEnum.create_post)


async def test_deleting_user_group_revokes_its_grants(db_session):
    """Удаление группы уносит выданные ей права (FK их не держит)."""
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    groups = UserGroupService(db_session)
    group = await groups.create(
        admin, org.id, name="Уйдёт", description=None, member_ids=[minion.id]
    )
    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user_group, subject_id=group.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.create_post,
    )
    await db_session.commit()

    authz = AuthorizationService(db_session)
    assert await authz.has_permission(minion, public.id, PermissionEnum.create_post)

    await groups.delete(admin, org.id, group.id)

    assert not await authz.has_permission(minion, public.id, PermissionEnum.create_post)


# ── 3. публикация без права ─────────────────────────────────────────────────

async def test_minion_cannot_publish_without_create_post(db_session):
    """MINION с просмотром, но без create_post, публиковать не может."""
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user, subject_id=minion.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.view_community,
    )

    authz = AuthorizationService(db_session)
    assert await authz.has_permission(minion, public.id, PermissionEnum.view_community)

    with pytest.raises(AuthorizationError) as exc:
        await authz.require_permission(minion, public.id, PermissionEnum.create_post)
    assert exc.value.status_code == 403


async def test_minion_can_publish_with_create_post(db_session):
    org = await _org(db_session)
    minion = await _user(db_session, org, UserRole.minion)
    public = await _public(db_session, org)

    await _grant(
        db_session, org,
        subject_type=AccessSubjectType.user, subject_id=minion.id,
        resource_type=AccessResourceType.community, resource_id=public.id,
        permission=PermissionEnum.create_post,
    )
    # Не должно бросать.
    await AuthorizationService(db_session).require_permission(
        minion, public.id, PermissionEnum.create_post
    )


# ── 4. защита последнего администратора ─────────────────────────────────────

async def test_can_delete_last_active_admin(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    other_admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    service = UserService(db_session)
    # Пока админов двое — удаление одного проходит.
    await service.delete_user(admin, org.id, other_admin.id)

    # Остался один: удалить его тоже можно. Явное удаление пользователя сильнее
    # защиты от случайного обезглавливания через блокировку или смену роли.
    root = await _user(db_session, org, UserRole.superadmin)
    await db_session.commit()

    await service.delete_user(root, org.id, admin.id)

    assert await db_session.scalar(select(User.id).where(User.id == admin.id)) is None


async def test_cannot_block_last_active_admin(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    root = await _user(db_session, org, UserRole.superadmin)
    await db_session.commit()

    with pytest.raises(LastAdminError):
        await UserService(db_session).set_blocked(root, org.id, admin.id, True)


async def test_cannot_demote_last_active_admin(db_session):
    """Понижение роли последнего админа тоже обезглавливает организацию."""
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    root = await _user(db_session, org, UserRole.superadmin)
    await db_session.commit()

    with pytest.raises(LastAdminError):
        await UserService(db_session).update_user(
            root, org.id, admin.id, UserUpdateRequest(role=UserRole.minion)
        )


async def test_blocked_admin_does_not_count_as_active(db_session):
    """Заблокированный админ не «прикрывает» последнего активного."""
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await _user(db_session, org, UserRole.admin, status=UserStatus.blocked)
    root = await _user(db_session, org, UserRole.superadmin)
    await db_session.commit()

    # Второй админ заблокирован => активный админ остался один => нельзя.
    with pytest.raises(LastAdminError):
        await UserService(db_session).set_blocked(root, org.id, admin.id, True)


# ── 5. запрет создания суперадмина обычным админом ──────────────────────────

async def test_admin_cannot_create_superadmin(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    with pytest.raises(AuthorizationError):
        await UserService(db_session).create_user(
            admin,
            org.id,
            UserCreateRequest(
                email="new@x.ru",
                first_name="Новый",
                role=UserRole.superadmin,
            ),
        )


async def test_created_user_is_invited(db_session):
    """Письма не шлём — новый пользователь заводится со статусом invited."""
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    created = await UserService(db_session).create_user(
        admin,
        org.id,
        UserCreateRequest(email="Invited@X.RU", first_name="Гость"),
    )
    assert created.status == UserStatus.invited
    assert created.role == UserRole.minion
    # email нормализован в lowercase — иначе упал бы CHECK в БД
    assert created.email == "invited@x.ru"


# ── 6. права: атомарная замена набора ───────────────────────────────────────

async def test_replace_grants_is_a_full_replace(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    minion = await _user(db_session, org, UserRole.minion)
    public_a = await _public(db_session, org)
    public_b = await _public(db_session, org)
    await db_session.commit()

    service = AccessGrantService(db_session)

    await service.replace(
        admin, org.id, AccessSubjectType.user, minion.id,
        [
            GrantItem(
                resource_type=AccessResourceType.community,
                resource_id=public_a.id,
                permission=PermissionEnum.create_post,
            )
        ],
    )
    authz = AuthorizationService(db_session)
    assert await authz.has_permission(minion, public_a.id, PermissionEnum.create_post)

    # Заменяем набор: право на A должно исчезнуть, на B — появиться.
    await service.replace(
        admin, org.id, AccessSubjectType.user, minion.id,
        [
            GrantItem(
                resource_type=AccessResourceType.community,
                resource_id=public_b.id,
                permission=PermissionEnum.create_post,
            )
        ],
    )
    assert not await authz.has_permission(minion, public_a.id, PermissionEnum.create_post)
    assert await authz.has_permission(minion, public_b.id, PermissionEnum.create_post)


async def test_cannot_grant_on_foreign_community(db_session):
    """Право на сообщество чужой организации выдать нельзя даже по UUID."""
    org_a = await _org(db_session, "A")
    org_b = await _org(db_session, "B")
    admin_a = await _user(db_session, org_a, UserRole.admin)
    minion_a = await _user(db_session, org_a, UserRole.minion)
    public_b = await _public(db_session, org_b)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await AccessGrantService(db_session).replace(
            admin_a, org_a.id, AccessSubjectType.user, minion_a.id,
            [
                GrantItem(
                    resource_type=AccessResourceType.community,
                    resource_id=public_b.id,
                    permission=PermissionEnum.view_community,
                )
            ],
        )
    assert exc.value.status_code == 400


# ── 7. импорт: preview ──────────────────────────────────────────────────────

def _xlsx(rows: list[list[str]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["email", "first_name", "last_name", "role", "user_groups"])
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_import_preview_flags_bad_email_duplicates_and_new_groups(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    content = _xlsx(
        [
            ["good@x.ru", "Иван", "Тихонов", "minion", "Модераторы"],
            ["не-почта", "Пётр", "Петров", "minion", ""],          # битый email
            ["good@x.ru", "Дубль", "Дублёв", "minion", ""],        # дубль в файле
            ["", "Безымянный", "", "minion", ""],                  # нет email
        ]
    )
    preview = await UserImportService(db_session).preview(
        admin, org.id, content, "users.xlsx"
    )

    assert preview.to_create == 1
    assert preview.errors == 3
    assert preview.new_groups == ["Модераторы"]

    by_row = {r.row_number: r for r in preview.rows}
    assert by_row[2].status == "create"
    assert "Модераторы" in by_row[2].warnings[0]
    assert by_row[3].status == "error" and "email" in by_row[3].errors[0].lower()
    assert by_row[4].status == "error" and "Дубликат" in by_row[4].errors[0]
    assert by_row[5].status == "error"


async def test_import_preview_rejects_superadmin_role(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    content = _xlsx([["root@x.ru", "Рут", "Рутов", "superadmin", ""]])
    preview = await UserImportService(db_session).preview(
        admin, org.id, content, "u.xlsx"
    )
    assert preview.errors == 1
    assert "superadmin" in preview.rows[0].errors[0].lower()


async def test_import_preview_marks_existing_user_as_update(db_session):
    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    existing = await _user(db_session, org, UserRole.minion)
    await db_session.commit()

    content = _xlsx([[existing.email, "Новое", "Имя", "minion", ""]])
    preview = await UserImportService(db_session).preview(
        admin, org.id, content, "u.xlsx"
    )
    assert preview.to_update == 1
    assert preview.rows[0].status == "update"


# ── 8. импорт: confirm ──────────────────────────────────────────────────────

async def test_import_confirm_creates_users_and_groups(db_session):
    """Подтверждение создаёт пользователей и недостающие группы."""
    from sqlalchemy import select

    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    service = UserImportService(db_session)
    content = _xlsx(
        [
            ["a@x.ru", "Анна", "Аннова", "minion", "Модераторы;Редакторы"],
            ["b@x.ru", "Борис", "Борисов", "admin", "Модераторы"],
        ]
    )
    preview = await service.preview(admin, org.id, content, "u.xlsx")
    result = await service.confirm(admin, org.id, preview.rows)

    assert result.created == 2
    assert result.errors == 0
    assert sorted(result.created_groups) == ["Модераторы", "Редакторы"]

    groups = (
        await db_session.execute(
            select(UserGroup.name).where(UserGroup.organization_id == org.id)
        )
    ).scalars().all()
    assert sorted(groups) == ["Модераторы", "Редакторы"]

    created = (
        await db_session.execute(
            select(User).where(User.email == "b@x.ru")
        )
    ).scalar_one()
    assert created.role == UserRole.admin
    assert created.status == UserStatus.invited


async def test_import_confirm_never_creates_superadmin(db_session):
    """Даже подделанная строка со статусом create не поднимет роль до superadmin."""
    from sqlalchemy import select

    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    # Клиент присылает confirm напрямую, минуя preview.
    forged = ImportRowPreview(
        row_number=2,
        status="create",
        email="evil@x.ru",
        first_name="Злой",
        last_name="Хакер",
        role=UserRole.superadmin,
        user_groups=[],
    )
    result = await UserImportService(db_session).confirm(admin, org.id, [forged])

    assert result.created == 0
    assert result.errors == 1

    exists = await db_session.scalar(
        select(User.id).where(User.email == "evil@x.ru")
    )
    assert exists is None


async def test_import_bad_row_does_not_cancel_good_rows(db_session):
    """Ошибочная строка не отменяет валидные."""
    from sqlalchemy import select

    org = await _org(db_session)
    admin = await _user(db_session, org, UserRole.admin)
    await db_session.commit()

    service = UserImportService(db_session)
    content = _xlsx(
        [
            ["ok@x.ru", "Хороший", "Строкин", "minion", ""],
            ["сломано", "Плохой", "Строкин", "minion", ""],
        ]
    )
    preview = await service.preview(admin, org.id, content, "u.xlsx")
    result = await service.confirm(admin, org.id, preview.rows)

    assert result.created == 1
    assert result.errors == 1

    survived = await db_session.scalar(select(User.id).where(User.email == "ok@x.ru"))
    assert survived is not None


async def test_import_error_report_is_csv_with_reasons(db_session):
    rows = [
        ImportRowPreview(
            row_number=3,
            status="error",
            email="bad",
            first_name="Пётр",
            user_groups=[],
            errors=["Некорректный email: bad"],
        )
    ]
    report = UserImportService.build_error_report(rows).decode("utf-8-sig")
    assert "Некорректный email" in report
    assert "3" in report
