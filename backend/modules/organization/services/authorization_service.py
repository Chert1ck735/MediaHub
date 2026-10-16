"""Серверная авторизация: роли и итоговые права на сообщества.

Единственный источник правды по доступам. Проверки живут ЗДЕСЬ, а не в UI:
прямой запрос в обход интерфейса обязан получить 403.

Правила (deny-правил в первом релизе нет — право есть только если найден грант):

* ``superadmin`` — проходит любую проверку, в любой организации;
* ``admin`` — полный доступ внутри СВОЕЙ организации (управление организацией
  следует из роли, а не из грантов), и ноль доступа к чужой;
* ``minion`` — ПРОСМОТР сообществ своей организации доступен по умолчанию;
  всё остальное — только по гранту.

Почему просмотр не выдаётся грантами: человек не может работать с тем, чего не
видит, и заводить грант на просмотр каждому сотруднику на каждое сообщество —
бессмысленная бухгалтерия. Гранты управляют тем, что МЕНЯЕТ мир: публикацией и
управлением сообществом. Изоляция организаций при этом сохраняется — чужие
сообщества не видны никому.

Итоговые права складываются из четырёх источников:

1. личный грант пользователя на сообщество;
2. личный грант пользователя на группу сообществ, куда входит сообщество;
3. грант группы пользователей (в которой состоит пользователь) на сообщество;
4. грант группы пользователей на группу сообществ, куда входит сообщество.

Всё это — ОДИН SQL-запрос (см. ``_grants_query``), а не обход групп в Python:
иначе на каждой проверке прав получили бы N+1.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.access_grants import AccessGrant
from backend.db.community_groups import CommunityGroupMember
from backend.db.enums import AccessResourceType, AccessSubjectType, PermissionEnum, UserRole
from backend.db.publics import Public
from backend.db.user_groups import UserGroup, UserGroupMember
from backend.db.users import User


@dataclass(frozen=True)
class EffectivePermission:
    """Право + откуда оно взялось (нужно экрану «итоговый доступ»)."""

    permission: PermissionEnum
    community_id: uuid.UUID
    # "direct" — выдано лично; "user_group" — унаследовано через группу.
    source_type: str
    source_name: str | None = None


class AuthorizationError(HTTPException):
    """403. Отдельный тип, чтобы не путать с 404 и не светить причину наружу."""

    def __init__(self, detail: str = "Недостаточно прав") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class AuthorizationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── роли ────────────────────────────────────────────────────────────────

    @staticmethod
    def is_superadmin(actor: User) -> bool:
        return actor.role == UserRole.superadmin

    @staticmethod
    def is_admin(actor: User) -> bool:
        return actor.role == UserRole.admin

    def require_superadmin(self, actor: User) -> None:
        if not self.is_superadmin(actor):
            raise AuthorizationError("Действие доступно только суперадминистратору")

    def require_organization_admin(self, actor: User, organization_id: uuid.UUID) -> None:
        """Актор вправе администрировать эту организацию.

        Суперадмин — любую. Админ — только свою. Миньон — никакую (настройки
        организации ему недоступны в принципе).
        """
        if self.is_superadmin(actor):
            return
        if not self.is_admin(actor):
            raise AuthorizationError("Настройки организации доступны только администратору")
        if actor.organization_id != organization_id:
            # Не уточняем, что организация существует, — это чужие данные.
            raise AuthorizationError("Нет доступа к этой организации")

    def require_can_manage_user(self, actor: User, target: User) -> None:
        """Админ не может трогать суперадминов и чужие организации."""
        self.require_organization_admin(actor, target.organization_id)
        if target.role == UserRole.superadmin and not self.is_superadmin(actor):
            raise AuthorizationError("Управлять суперадминистратором может только суперадминистратор")

    def require_role_assignable(self, actor: User, role: UserRole) -> None:
        """Роль, которую актор вправе назначить. Админ не производит суперадминов."""
        if role == UserRole.superadmin and not self.is_superadmin(actor):
            raise AuthorizationError("Назначить роль суперадминистратора может только суперадминистратор")

    # ── права на сообщества ─────────────────────────────────────────────────

    @staticmethod
    def _grants_query(user_id: uuid.UUID) -> Select:
        """Гранты, действующие на пользователя: личные + через его группы.

        Ресурс не фиксируем — вызывающий сам сузит по сообществу либо получит
        все. Подзапрос по членству вместо join'а: грант может быть личным, и
        тогда join по группам вырезал бы его.
        """
        user_group_ids = select(UserGroupMember.user_group_id).where(
            UserGroupMember.user_id == user_id
        )
        return select(AccessGrant).where(
            or_(
                (AccessGrant.subject_type == AccessSubjectType.user)
                & (AccessGrant.subject_id == user_id),
                (AccessGrant.subject_type == AccessSubjectType.user_group)
                & (AccessGrant.subject_id.in_(user_group_ids)),
            )
        )

    async def get_effective_permissions(
        self,
        user_id: uuid.UUID,
        community_id: uuid.UUID,
    ) -> set[PermissionEnum]:
        """Итоговые права пользователя на конкретное сообщество.

        Роли здесь НЕ учитываются — это чистое сложение грантов. Роль
        обрабатывает ``has_permission``: иначе суперадмин, у которого нет ни
        одного гранта, «терял» бы доступ.
        """
        community_group_ids = select(CommunityGroupMember.community_group_id).where(
            CommunityGroupMember.public_id == community_id
        )
        stmt = self._grants_query(user_id).where(
            or_(
                (AccessGrant.resource_type == AccessResourceType.community)
                & (AccessGrant.resource_id == community_id),
                (AccessGrant.resource_type == AccessResourceType.community_group)
                & (AccessGrant.resource_id.in_(community_group_ids)),
            )
        )
        rows = (await self._db.execute(stmt)).scalars().all()
        return {row.permission for row in rows}

    async def has_permission(
        self,
        actor: User,
        community_id: uuid.UUID,
        permission: PermissionEnum,
    ) -> bool:
        """Есть ли у актора право на сообщество — с учётом роли."""
        if self.is_superadmin(actor):
            return True

        community = await self._db.get(Public, community_id)
        if community is None:
            return False

        # Чужая организация — мимо, какие бы гранты ни висели.
        if actor.organization_id != community.organization_id:
            return False

        # Админ распоряжается сообществами своей организации по роли.
        if self.is_admin(actor):
            return True

        # ПРОСМОТР сообществ своей организации доступен каждому сотруднику по
        # умолчанию — это не привилегия, а условие работы: человек не может
        # анализировать то, чего не видит. Грантами управляется только то, что
        # МЕНЯЕТ мир: публикация и управление сообществом.
        if permission == PermissionEnum.view_community:
            return True

        return permission in await self.get_effective_permissions(actor.id, community_id)

    async def require_permission(
        self,
        actor: User,
        community_id: uuid.UUID,
        permission: PermissionEnum,
    ) -> None:
        """Бросает 403, если права нет. Точка входа для защиты ручек."""
        if not await self.has_permission(actor, community_id, permission):
            raise AuthorizationError("Нет доступа к этому сообществу")

    async def list_accessible_community_ids(
        self,
        actor: User,
        permission: PermissionEnum = PermissionEnum.view_community,
    ) -> list[uuid.UUID] | None:
        """Сообщества, доступные актору с данным правом.

        ``None`` — «все сообщества организации»: вызывающий не должен
        фильтровать. Пустой список — доступа нет ни к одному. Возвращать None
        вместо полного перечня дёшево и не врёт при росте числа сообществ.
        """
        if self.is_superadmin(actor) or self.is_admin(actor):
            return None

        # Просмотр открыт всем сотрудникам организации (см. has_permission),
        # поэтому фильтровать список по грантам нечего.
        if permission == PermissionEnum.view_community:
            return None

        stmt = self._grants_query(actor.id).where(AccessGrant.permission == permission)
        grants = (await self._db.execute(stmt)).scalars().all()

        direct_ids = {
            g.resource_id for g in grants
            if g.resource_type == AccessResourceType.community
        }
        group_ids = [
            g.resource_id for g in grants
            if g.resource_type == AccessResourceType.community_group
        ]
        if group_ids:
            via_groups = (
                await self._db.execute(
                    select(CommunityGroupMember.public_id).where(
                        CommunityGroupMember.community_group_id.in_(group_ids)
                    )
                )
            ).scalars().all()
            direct_ids.update(via_groups)

        return list(direct_ids)

    async def describe_effective_access(self, user: User) -> list[EffectivePermission]:
        """Итоговые доступы пользователя с указанием источника права.

        Для экрана «эффективный доступ»: показываем, выдано право лично или
        унаследовано через группу — унаследованное нельзя редактировать как
        индивидуальное.
        """
        grants = (await self._db.execute(self._grants_query(user.id))).scalars().all()
        if not grants:
            return []

        # Имена групп-субъектов — одним запросом, не по одному на грант.
        group_subject_ids = {
            g.subject_id for g in grants
            if g.subject_type == AccessSubjectType.user_group
        }
        group_names: dict[uuid.UUID, str] = {}
        if group_subject_ids:
            rows = (
                await self._db.execute(
                    select(UserGroup.id, UserGroup.name).where(UserGroup.id.in_(group_subject_ids))
                )
            ).all()
            group_names = {row.id: row.name for row in rows}

        # Раскрываем группы сообществ в конкретные сообщества — тоже одним запросом.
        resource_group_ids = {
            g.resource_id for g in grants
            if g.resource_type == AccessResourceType.community_group
        }
        members: dict[uuid.UUID, list[uuid.UUID]] = {}
        if resource_group_ids:
            rows = (
                await self._db.execute(
                    select(
                        CommunityGroupMember.community_group_id,
                        CommunityGroupMember.public_id,
                    ).where(CommunityGroupMember.community_group_id.in_(resource_group_ids))
                )
            ).all()
            for group_id, public_id in rows:
                members.setdefault(group_id, []).append(public_id)

        out: list[EffectivePermission] = []
        for grant in grants:
            if grant.subject_type == AccessSubjectType.user:
                source_type, source_name = "direct", None
            else:
                source_type = "user_group"
                source_name = group_names.get(grant.subject_id)

            if grant.resource_type == AccessResourceType.community:
                community_ids = [grant.resource_id]
            else:
                community_ids = members.get(grant.resource_id, [])

            for community_id in community_ids:
                out.append(
                    EffectivePermission(
                        permission=grant.permission,
                        community_id=community_id,
                        source_type=source_type,
                        source_name=source_name,
                    )
                )
        return out
