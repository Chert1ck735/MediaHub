"""Выдача и отзыв прав.

Сохранение — атомарный REPLACE набора грантов субъекта, а не add/remove по
одному: UI редактирует матрицу целиком, и инкрементальные операции разъезжаются
с ней, если параллельно открыты две вкладки. Всё в одной транзакции — либо
новый набор целиком, либо старый остаётся нетронутым.

Гранты полиморфны и не имеют настоящих FK, поэтому существование и организацию
субъекта/ресурса проверяем ЗДЕСЬ (БД этого не сделает). Пропустить проверку —
значит позволить выдать право на чужое сообщество по угаданному UUID.
"""
from __future__ import annotations

import uuid
from typing import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.access_grants import AccessGrant
from backend.db.community_groups import CommunityGroup
from backend.db.enums import AccessResourceType, AccessSubjectType
from backend.db.publics import Public
from backend.db.user_groups import UserGroup
from backend.db.users import User
from backend.modules.organization.schemas import GrantItem
from backend.modules.organization.services.audit_service import AuditService
from backend.modules.organization.services.authorization_service import AuthorizationService


class AccessGrantService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)
        self._audit = AuditService(db)

    async def _validate_subject(
        self,
        organization_id: uuid.UUID,
        subject_type: AccessSubjectType,
        subject_id: uuid.UUID,
    ) -> None:
        if subject_type == AccessSubjectType.user:
            exists = await self._db.scalar(
                select(User.id).where(
                    User.id == subject_id,
                    User.organization_id == organization_id,
                )
            )
        else:
            exists = await self._db.scalar(
                select(UserGroup.id).where(
                    UserGroup.id == subject_id,
                    UserGroup.organization_id == organization_id,
                )
            )
        if exists is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Субъект прав не найден в этой организации",
            )

    async def _validate_resources(
        self,
        organization_id: uuid.UUID,
        grants: Sequence[GrantItem],
    ) -> None:
        """Проверяет все ресурсы двумя запросами, а не по одному на грант."""
        community_ids = {
            g.resource_id for g in grants
            if g.resource_type == AccessResourceType.community
        }
        group_ids = {
            g.resource_id for g in grants
            if g.resource_type == AccessResourceType.community_group
        }

        if community_ids:
            found = set(
                (
                    await self._db.execute(
                        select(Public.id).where(
                            Public.id.in_(community_ids),
                            Public.organization_id == organization_id,
                        )
                    )
                ).scalars().all()
            )
            if community_ids - found:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Указаны сообщества не из этой организации",
                )

        if group_ids:
            found = set(
                (
                    await self._db.execute(
                        select(CommunityGroup.id).where(
                            CommunityGroup.id.in_(group_ids),
                            CommunityGroup.organization_id == organization_id,
                        )
                    )
                ).scalars().all()
            )
            if group_ids - found:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Указаны группы сообществ не из этой организации",
                )

    async def get_matrix(
        self,
        actor: User,
        organization_id: uuid.UUID,
        subject_type: AccessSubjectType,
        subject_id: uuid.UUID,
    ) -> list[AccessGrant]:
        self._authz.require_organization_admin(actor, organization_id)
        await self._validate_subject(organization_id, subject_type, subject_id)

        return list(
            (
                await self._db.execute(
                    select(AccessGrant).where(
                        AccessGrant.organization_id == organization_id,
                        AccessGrant.subject_type == subject_type,
                        AccessGrant.subject_id == subject_id,
                    )
                )
            ).scalars().all()
        )

    async def replace(
        self,
        actor: User,
        organization_id: uuid.UUID,
        subject_type: AccessSubjectType,
        subject_id: uuid.UUID,
        grants: Sequence[GrantItem],
    ) -> list[AccessGrant]:
        """Приводит набор грантов субъекта ровно к переданному.

        Трогает ТОЛЬКО гранты этого субъекта: чужие назначения (другому
        пользователю или группе) не затрагиваются.
        """
        self._authz.require_organization_admin(actor, organization_id)
        await self._validate_subject(organization_id, subject_type, subject_id)
        await self._validate_resources(organization_id, grants)

        existing = await self.get_matrix(actor, organization_id, subject_type, subject_id)
        current = {
            (g.resource_type, g.resource_id, g.permission): g for g in existing
        }
        desired = {
            (g.resource_type, g.resource_id, g.permission) for g in grants
        }

        added = desired - current.keys()
        removed = current.keys() - desired

        for key in removed:
            await self._db.delete(current[key])

        for resource_type, resource_id, permission in added:
            self._db.add(
                AccessGrant(
                    organization_id=organization_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    permission=permission,
                )
            )

        if added or removed:
            self._audit.record(
                organization_id=organization_id,
                actor_user_id=actor.id,
                entity_type="access_grant",
                entity_id=subject_id,
                action="replace",
                before={
                    "subject_type": subject_type.value,
                    "grants": [
                        f"{r_type.value}:{r_id}:{perm.value}"
                        for r_type, r_id, perm in current.keys()
                    ],
                },
                after={
                    "subject_type": subject_type.value,
                    "grants": [
                        f"{r_type.value}:{r_id}:{perm.value}"
                        for r_type, r_id, perm in desired
                    ],
                    "added": len(added),
                    "removed": len(removed),
                },
            )

        await self._db.commit()
        return await self.get_matrix(actor, organization_id, subject_type, subject_id)
