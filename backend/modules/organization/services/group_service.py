"""Группы пользователей и группы сообществ.

Оба вида групп ведут себя одинаково: CRUD + замена состава + удаление вместе с
выданными на них грантами. Общая часть вынесена в ``_GroupServiceBase``.

Важно про удаление: гранты ссылаются на группу полиморфным ``subject_id`` /
``resource_id`` без настоящего FK, поэтому БД их НЕ уберёт каскадом. Если этого
не сделать руками — права, унаследованные через группу, останутся висеть
мусором. Отзыв доступа при удалении группы — требование ТЗ.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.access_grants import AccessGrant
from backend.db.community_groups import CommunityGroup, CommunityGroupMember
from backend.db.enums import AccessResourceType, AccessSubjectType
from backend.db.publics import Public
from backend.db.user_groups import UserGroup, UserGroupMember
from backend.db.users import User
from backend.modules.organization.services.audit_service import AuditService
from backend.modules.organization.services.authorization_service import AuthorizationService


class _GroupServiceBase:
    """Общая механика для обоих видов групп."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)
        self._audit = AuditService(db)

    async def _delete_grants(
        self,
        *,
        subject_type: AccessSubjectType | None = None,
        resource_type: AccessResourceType | None = None,
        entity_id: uuid.UUID,
    ) -> int:
        """Сносит гранты, где группа выступает субъектом или ресурсом."""
        if subject_type is not None:
            stmt = select(AccessGrant).where(
                AccessGrant.subject_type == subject_type,
                AccessGrant.subject_id == entity_id,
            )
        else:
            stmt = select(AccessGrant).where(
                AccessGrant.resource_type == resource_type,
                AccessGrant.resource_id == entity_id,
            )
        grants = (await self._db.execute(stmt)).scalars().all()
        for grant in grants:
            await self._db.delete(grant)
        return len(grants)


class UserGroupService(_GroupServiceBase):
    """Группы пользователей."""

    async def get(self, organization_id: uuid.UUID, group_id: uuid.UUID) -> UserGroup:
        group = (
            await self._db.execute(
                select(UserGroup).where(
                    UserGroup.id == group_id,
                    UserGroup.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа не найдена")
        return group

    async def list_groups(self, organization_id: uuid.UUID) -> list[tuple[UserGroup, int, int]]:
        """Группы + число участников + число выданных им прав.

        Счётчики считаем агрегатами в SQL: тянуть состав каждой группы в Python
        ради len() — это N+1 на ровном месте.
        """
        member_counts = (
            select(
                UserGroupMember.user_group_id.label("gid"),
                func.count().label("cnt"),
            )
            .group_by(UserGroupMember.user_group_id)
            .subquery()
        )
        grant_counts = (
            select(
                AccessGrant.subject_id.label("gid"),
                func.count().label("cnt"),
            )
            .where(AccessGrant.subject_type == AccessSubjectType.user_group)
            .group_by(AccessGrant.subject_id)
            .subquery()
        )
        stmt = (
            select(
                UserGroup,
                func.coalesce(member_counts.c.cnt, 0),
                func.coalesce(grant_counts.c.cnt, 0),
            )
            .outerjoin(member_counts, member_counts.c.gid == UserGroup.id)
            .outerjoin(grant_counts, grant_counts.c.gid == UserGroup.id)
            .where(UserGroup.organization_id == organization_id)
            .order_by(UserGroup.name.asc())
        )
        return [tuple(row) for row in (await self._db.execute(stmt)).all()]

    async def create(
        self,
        actor: User,
        organization_id: uuid.UUID,
        *,
        name: str,
        description: str | None,
        member_ids: Sequence[uuid.UUID],
    ) -> UserGroup:
        self._authz.require_organization_admin(actor, organization_id)

        group = UserGroup(
            organization_id=organization_id,
            name=name.strip(),
            description=description,
        )
        self._db.add(group)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Группа с таким названием уже существует"
            ) from exc

        await self._set_members(group, member_ids, organization_id)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user_group",
            entity_id=group.id,
            action="create",
            after={"name": group.name, "description": group.description,
                   "members": len(member_ids)},
        )
        await self._db.commit()
        return group

    async def update(
        self,
        actor: User,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        name: str,
        description: str | None,
        member_ids: Sequence[uuid.UUID],
    ) -> UserGroup:
        self._authz.require_organization_admin(actor, organization_id)
        group = await self.get(organization_id, group_id)

        before = {"name": group.name, "description": group.description}
        group.name = name.strip()
        group.description = description

        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Группа с таким названием уже существует"
            ) from exc

        await self._set_members(group, member_ids, organization_id)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user_group",
            entity_id=group.id,
            action="update",
            before=before,
            after={"name": group.name, "description": group.description,
                   "members": len(member_ids)},
        )
        await self._db.commit()
        return group

    async def delete(
        self,
        actor: User,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        self._authz.require_organization_admin(actor, organization_id)
        group = await self.get(organization_id, group_id)

        # Права, выданные группе, отзываются вместе с ней — их не удержит FK.
        revoked = await self._delete_grants(
            subject_type=AccessSubjectType.user_group, entity_id=group.id
        )

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user_group",
            entity_id=group.id,
            action="delete",
            before={"name": group.name, "revoked_grants": revoked},
        )
        await self._db.delete(group)  # состав уйдёт по FK CASCADE
        await self._db.commit()

    async def _set_members(
        self,
        group: UserGroup,
        member_ids: Sequence[uuid.UUID],
        organization_id: uuid.UUID,
    ) -> None:
        requested = set(member_ids)
        if requested:
            found = set(
                (
                    await self._db.execute(
                        select(User.id).where(
                            User.id.in_(requested),
                            User.organization_id == organization_id,
                        )
                    )
                ).scalars().all()
            )
            if requested - found:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Указаны пользователи не из этой организации",
                )

        current = set(
            (
                await self._db.execute(
                    select(UserGroupMember.user_id).where(
                        UserGroupMember.user_group_id == group.id
                    )
                )
            ).scalars().all()
        )
        for user_id in requested - current:
            self._db.add(
                UserGroupMember(
                    user_group_id=group.id,
                    user_id=user_id,
                    organization_id=organization_id,
                )
            )
        for user_id in current - requested:
            member = await self._db.get(UserGroupMember, (group.id, user_id))
            if member is not None:
                await self._db.delete(member)
        await self._db.flush()

    async def get_member_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            (
                await self._db.execute(
                    select(UserGroupMember.user_id).where(
                        UserGroupMember.user_group_id == group_id
                    )
                )
            ).scalars().all()
        )


class CommunityGroupService(_GroupServiceBase):
    """Группы сообществ. Сообщество — это ``Public``."""

    async def get(self, organization_id: uuid.UUID, group_id: uuid.UUID) -> CommunityGroup:
        group = (
            await self._db.execute(
                select(CommunityGroup).where(
                    CommunityGroup.id == group_id,
                    CommunityGroup.organization_id == organization_id,
                )
            )
        ).scalar_one_or_none()
        if group is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Группа сообществ не найдена")
        return group

    async def list_groups(
        self, organization_id: uuid.UUID
    ) -> list[tuple[CommunityGroup, int, int]]:
        member_counts = (
            select(
                CommunityGroupMember.community_group_id.label("gid"),
                func.count().label("cnt"),
            )
            .group_by(CommunityGroupMember.community_group_id)
            .subquery()
        )
        grant_counts = (
            select(AccessGrant.resource_id.label("gid"), func.count().label("cnt"))
            .where(AccessGrant.resource_type == AccessResourceType.community_group)
            .group_by(AccessGrant.resource_id)
            .subquery()
        )
        stmt = (
            select(
                CommunityGroup,
                func.coalesce(member_counts.c.cnt, 0),
                func.coalesce(grant_counts.c.cnt, 0),
            )
            .outerjoin(member_counts, member_counts.c.gid == CommunityGroup.id)
            .outerjoin(grant_counts, grant_counts.c.gid == CommunityGroup.id)
            .where(CommunityGroup.organization_id == organization_id)
            .order_by(CommunityGroup.name.asc())
        )
        return [tuple(row) for row in (await self._db.execute(stmt)).all()]

    async def create(
        self,
        actor: User,
        organization_id: uuid.UUID,
        *,
        name: str,
        description: str | None,
        community_ids: Sequence[uuid.UUID],
    ) -> CommunityGroup:
        self._authz.require_organization_admin(actor, organization_id)

        group = CommunityGroup(
            organization_id=organization_id,
            name=name.strip(),
            description=description,
        )
        self._db.add(group)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Группа с таким названием уже существует"
            ) from exc

        await self._set_communities(group, community_ids, organization_id)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="community_group",
            entity_id=group.id,
            action="create",
            after={"name": group.name, "communities": len(community_ids)},
        )
        await self._db.commit()
        return group

    async def update(
        self,
        actor: User,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        name: str,
        description: str | None,
        community_ids: Sequence[uuid.UUID],
    ) -> CommunityGroup:
        self._authz.require_organization_admin(actor, organization_id)
        group = await self.get(organization_id, group_id)

        before = {"name": group.name, "description": group.description}
        group.name = name.strip()
        group.description = description

        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Группа с таким названием уже существует"
            ) from exc

        await self._set_communities(group, community_ids, organization_id)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="community_group",
            entity_id=group.id,
            action="update",
            before=before,
            after={"name": group.name, "communities": len(community_ids)},
        )
        await self._db.commit()
        return group

    async def delete(
        self,
        actor: User,
        organization_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        self._authz.require_organization_admin(actor, organization_id)
        group = await self.get(organization_id, group_id)

        # Гранты, выданные НА эту группу сообществ, отзываются вместе с ней.
        revoked = await self._delete_grants(
            resource_type=AccessResourceType.community_group, entity_id=group.id
        )

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="community_group",
            entity_id=group.id,
            action="delete",
            before={"name": group.name, "revoked_grants": revoked},
        )
        await self._db.delete(group)
        await self._db.commit()

    async def _set_communities(
        self,
        group: CommunityGroup,
        community_ids: Sequence[uuid.UUID],
        organization_id: uuid.UUID,
    ) -> None:
        requested = set(community_ids)
        if requested:
            found = set(
                (
                    await self._db.execute(
                        select(Public.id).where(
                            Public.id.in_(requested),
                            Public.organization_id == organization_id,
                        )
                    )
                ).scalars().all()
            )
            if requested - found:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Указаны сообщества не из этой организации",
                )

        current = set(
            (
                await self._db.execute(
                    select(CommunityGroupMember.public_id).where(
                        CommunityGroupMember.community_group_id == group.id
                    )
                )
            ).scalars().all()
        )
        for public_id in requested - current:
            self._db.add(
                CommunityGroupMember(
                    community_group_id=group.id,
                    public_id=public_id,
                    organization_id=organization_id,
                )
            )
        for public_id in current - requested:
            member = await self._db.get(CommunityGroupMember, (group.id, public_id))
            if member is not None:
                await self._db.delete(member)
        await self._db.flush()

    async def get_community_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        return list(
            (
                await self._db.execute(
                    select(CommunityGroupMember.public_id).where(
                        CommunityGroupMember.community_group_id == group_id
                    )
                )
            ).scalars().all()
        )
