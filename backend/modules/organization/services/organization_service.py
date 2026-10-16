"""Организации: создание, список, правка.

Раньше организация появлялась только как побочный эффект регистрации первого
пользователя. Теперь это явная операция — но заводить организации может ТОЛЬКО
суперадмин: иначе любой админ бесконтрольно плодит организации и сам себе
раздаёт в них права.

Админ видит и правит только свою; суперадмин — все.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import OrgType, UserRole, UserStatus
from backend.db.organizations import Organization
from backend.db.publics import Public
from backend.db.regions import Region
from backend.db.users import User
from backend.modules.organization.municipalities import (
    canonical_municipality_name,
    is_krasnoyarsk_region_name,
)
from backend.modules.organization.services.audit_service import AuditService
from backend.modules.organization.services.authorization_service import AuthorizationService

logger = logging.getLogger(__name__)


class OrganizationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)
        self._audit = AuditService(db)

    async def list_organizations(self, actor: User) -> list[tuple[Organization, int, int]]:
        """Организации, доступные актору, + счётчики пользователей и площадок.

        Счётчики считаем агрегатами в SQL: тянуть коллекции ради len() — это
        N+1 на ровном месте.
        """
        user_counts = (
            select(User.organization_id.label("oid"), func.count().label("cnt"))
            .group_by(User.organization_id)
            .subquery()
        )
        public_counts = (
            select(Public.organization_id.label("oid"), func.count().label("cnt"))
            .group_by(Public.organization_id)
            .subquery()
        )
        stmt = (
            select(
                Organization,
                func.coalesce(user_counts.c.cnt, 0),
                func.coalesce(public_counts.c.cnt, 0),
            )
            .outerjoin(user_counts, user_counts.c.oid == Organization.id)
            .outerjoin(public_counts, public_counts.c.oid == Organization.id)
            .order_by(Organization.name.asc())
        )

        # Админ видит только свою организацию — чужие названия ему не показываем.
        if not self._authz.is_superadmin(actor):
            if actor.organization_id is None:
                return []
            stmt = stmt.where(Organization.id == actor.organization_id)

        return [tuple(row) for row in (await self._db.execute(stmt)).all()]

    async def get(self, actor: User, organization_id: uuid.UUID) -> Organization:
        self._authz.require_organization_admin(actor, organization_id)
        org = await self._db.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Организация не найдена")
        return org

    async def create(
        self,
        actor: User,
        *,
        name: str,
        org_type: OrgType,
        description: str | None,
        region_id: uuid.UUID | None = None,
        municipality_name: str | None = None,
        admin_email: str | None = None,
        admin_first_name: str | None = None,
        admin_last_name: str | None = None,
        public_base_url: str | None = None,
    ) -> Organization:
        """Заводит организацию и (опционально) сразу её администратора.

        Организация без администратора бесполезна: управлять ею будет некому,
        кроме суперадмина. Поэтому админа можно создать тем же действием.
        """
        self._authz.require_superadmin(actor)
        region = await self._resolve_region(region_id)
        municipality = self._normalize_municipality(municipality_name, region)

        org = Organization(
            name=name.strip(),
            type=org_type,
            description=description,
            region_id=region.id if region else None,
            municipality_name=municipality,
            is_active=True,
        )
        self._db.add(org)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Организация с таким названием уже существует"
            ) from exc

        created_admin: User | None = None
        if admin_email:
            # Импорт здесь, а не наверху: UserService импортирует authorization,
            # и на верхнем уровне вышел бы циклический импорт.
            from backend.modules.auth.services.password_service import PasswordService
            import secrets

            email = admin_email.strip().lower()
            existing = await self._db.scalar(select(User.id).where(User.email == email))
            if existing is not None:
                await self._db.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Пользователь с такой почтой уже существует",
                )

            created_admin = User(
                email=email,
                first_name=(admin_first_name or "Администратор").strip(),
                last_name=(admin_last_name or "").strip(),
                role=UserRole.admin,
                status=UserStatus.invited,
                organization_id=org.id,
                # Пароль задаётся при принятии приглашения. Случайный, а не
                # пустой: иначе получится учётка с предсказуемым входом.
                password_hash=PasswordService().hash_password(secrets.token_urlsafe(32)),
                created_by=actor.id,
            )
            self._db.add(created_admin)
            await self._db.flush()

        self._audit.record(
            organization_id=org.id,
            actor_user_id=actor.id,
            entity_type="organization",
            entity_id=org.id,
            action="create",
            after={
                "name": org.name,
                "type": org.type,
                "description": org.description,
                "region_id": str(org.region_id) if org.region_id else None,
                "municipality_name": org.municipality_name,
                "admin_email": created_admin.email if created_admin else None,
            },
        )
        if created_admin is not None:
            from backend.modules.auth.services.invitation_service import InvitationService

            await InvitationService(self._db).issue(
                created_admin,
                invited_by=actor.id,
                public_base_url=public_base_url,
            )
        else:
            await self._db.commit()
        await self._db.refresh(org)
        return org

    async def update(
        self,
        actor: User,
        organization_id: uuid.UUID,
        *,
        name: str | None = None,
        org_type: OrgType | None = None,
        description: str | None = None,
        region_id: uuid.UUID | None = None,
        region_id_set: bool = False,
        municipality_name: str | None = None,
        municipality_name_set: bool = False,
        is_active: bool | None = None,
    ) -> Organization:
        """Правка организации. Админ — только свою; деактивация — суперадмин."""
        org = await self.get(actor, organization_id)

        before = {
            "name": org.name,
            "type": org.type,
            "description": org.description,
            "region_id": str(org.region_id) if org.region_id else None,
            "municipality_name": org.municipality_name,
            "is_active": org.is_active,
        }

        if name is not None:
            org.name = name.strip()
        if description is not None:
            org.description = description

        if org_type is not None and org_type != org.type:
            # Тип организации меняет только суперадмин: он определяет, как
            # организация трактуется системой, и админ не должен переписывать
            # собственную категорию.
            self._authz.require_superadmin(actor)
            org.type = org_type

        if region_id_set:
            region = await self._resolve_region(region_id)
            org.region_id = region.id if region else None
            if not is_krasnoyarsk_region_name(region.name if region else None):
                org.municipality_name = None

        if municipality_name_set:
            region = await self._region_by_id(org.region_id)
            org.municipality_name = self._normalize_municipality(
                municipality_name,
                region,
            )

        if is_active is not None:
            # Отключить организацию = отрезать всех её пользователей. Такое
            # решение принимает только суперадмин.
            self._authz.require_superadmin(actor)
            org.is_active = is_active

        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Организация с таким названием уже существует"
            ) from exc

        self._audit.record(
            organization_id=org.id,
            actor_user_id=actor.id,
            entity_type="organization",
            entity_id=org.id,
            action="update",
            before=before,
            after={
                "name": org.name,
                "type": org.type,
                "description": org.description,
                "region_id": str(org.region_id) if org.region_id else None,
                "municipality_name": org.municipality_name,
                "is_active": org.is_active,
            },
        )
        await self._db.commit()
        await self._db.refresh(org)
        return org

    async def delete(self, actor: User, organization_id: uuid.UUID) -> None:
        """Удаляет организацию. Только суперадмин.

        Это разрушительная операция: по каскадам уходят её пользователи,
        площадки, группы и гранты. Собственную организацию удалить нельзя —
        суперадмин отрезал бы сам себя.
        """
        self._authz.require_superadmin(actor)

        org = await self._db.get(Organization, organization_id)
        if org is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Организация не найдена")

        if actor.organization_id == organization_id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Нельзя удалить организацию, в которой вы состоите",
            )

        # Аудит организации уйдёт вместе с ней по каскаду — записываем ДО
        # удаления, чтобы след остался хотя бы в логе приложения.
        logger.warning(
            "Организация удалена | id=%s | name=%s | actor=%s",
            org.id,
            org.name,
            actor.id,
        )

        await self._db.delete(org)
        await self._db.commit()

    async def _resolve_region(self, region_id: uuid.UUID | None) -> Region | None:
        if region_id is None:
            return None
        region = await self._region_by_id(region_id)
        if region is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Регион не найден")
        return region

    async def _region_by_id(self, region_id: uuid.UUID | None) -> Region | None:
        if region_id is None:
            return None
        return await self._db.get(Region, region_id)

    def _normalize_municipality(
        self,
        municipality_name: str | None,
        region: Region | None,
    ) -> str | None:
        raw = (municipality_name or "").strip()
        if not raw:
            return None
        if not is_krasnoyarsk_region_name(region.name if region else None):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Муниципалитет можно выбрать только для Красноярского края",
            )
        canonical = canonical_municipality_name(raw)
        if canonical is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Неизвестный муниципалитет Красноярского края",
            )
        return canonical
