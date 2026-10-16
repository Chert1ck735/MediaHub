"""Пользователи организации: список, создание, изменение, блокировка, удаление.

Защита последнего администратора работает для блокировки и смены роли. Удаление
пользователя остаётся явной разрушительной операцией и может оставить организацию без админа.
"""
from __future__ import annotations

import secrets
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.access_grants import AccessGrant
from backend.db.enums import AccessSubjectType, PermissionEnum, UserRole, UserStatus
from backend.db.user_groups import UserGroup, UserGroupMember
from backend.db.users import User
from backend.modules.auth.services.password_service import PasswordService
from backend.modules.auth.services.invitation_service import InvitationService
from backend.modules.organization.schemas import UserCreateRequest, UserUpdateRequest
from backend.modules.organization.services.audit_service import AuditService
from backend.modules.organization.services.authorization_service import AuthorizationService


class LastAdminError(HTTPException):
    """409: организация не может остаться без активного администратора."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="В организации должен остаться хотя бы один активный администратор",
        )


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._authz = AuthorizationService(db)
        self._audit = AuditService(db)
        self._passwords = PasswordService()

    # ── чтение ──────────────────────────────────────────────────────────────

    async def get_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
        """Пользователь СВОЕЙ организации. Чужой — 404, а не 403.

        Отвечать 403 на чужого пользователя — значит подтверждать, что он
        существует. Наружу такие вещи не подтверждаем.
        """
        stmt = (
            select(User)
            .where(User.id == user_id, User.organization_id == organization_id)
            .options(selectinload(User.groups))
        )
        user = (await self._db.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Пользователь не найден",
            )
        return user

    async def list_users(
        self,
        organization_id: uuid.UUID,
        *,
        search: str | None = None,
        role: UserRole | None = None,
        user_status: UserStatus | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[User], int]:
        """Страница пользователей + общее число. Поиск по ФИО и email."""
        conditions = [User.organization_id == organization_id]

        if search:
            pattern = f"%{search.strip().lower()}%"
            conditions.append(
                or_(
                    func.lower(User.email).like(pattern),
                    func.lower(User.first_name).like(pattern),
                    func.lower(User.last_name).like(pattern),
                    # Поиск по «Иван Тихонов» целиком, а не только по частям.
                    func.lower(User.first_name + " " + User.last_name).like(pattern),
                )
            )
        if role is not None:
            conditions.append(User.role == role)
        if user_status is not None:
            conditions.append(User.status == user_status)

        total = int(
            await self._db.scalar(
                select(func.count()).select_from(User).where(*conditions)
            )
            or 0
        )

        page = max(1, page)
        page_size = min(max(1, page_size), 200)
        stmt = (
            select(User)
            .where(*conditions)
            .options(selectinload(User.groups))  # иначе N+1 на группах в списке
            .order_by(User.last_name.asc(), User.first_name.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        users = (await self._db.execute(stmt)).scalars().all()
        return list(users), total

    async def list_for_export(
        self,
        organization_id: uuid.UUID,
        *,
        limit: int = 5000,
    ) -> list[User]:
        """Все пользователи организации — для выгрузки в файл.

        Отдельный метод, а не ``list_users`` с огромным page_size: там потолок
        страницы (200) стоит намеренно, чтобы кривой запрос не выгреб всю
        таблицу в память. Экспорт — законное исключение, но и у него есть
        верхняя планка.
        """
        stmt = (
            select(User)
            .where(User.organization_id == organization_id)
            .options(selectinload(User.groups))  # иначе N+1 на группах при выгрузке
            .order_by(User.last_name.asc(), User.first_name.asc())
            .limit(limit)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    # ── защита последнего админа ────────────────────────────────────────────

    async def _count_other_active_admins(
        self,
        organization_id: uuid.UUID,
        exclude_user_id: uuid.UUID,
    ) -> int:
        """Сколько ещё активных админов останется, если не считать этого."""
        return int(
            await self._db.scalar(
                select(func.count())
                .select_from(User)
                .where(
                    User.organization_id == organization_id,
                    User.id != exclude_user_id,
                    User.role == UserRole.admin,
                    User.status == UserStatus.active,
                )
            )
            or 0
        )

    async def _guard_last_admin(self, user: User) -> None:
        """Не даёт «обезглавить» организацию.

        Срабатывает, если пользователь СЕЙЧАС активный админ и после операции
        (блокировка / смена роли) активных админов не останется.
        """
        is_active_admin = user.role == UserRole.admin and user.status == UserStatus.active
        if not is_active_admin:
            return
        if await self._count_other_active_admins(user.organization_id, user.id) == 0:
            raise LastAdminError()

    # ── запись ──────────────────────────────────────────────────────────────

    async def create_user(
        self,
        actor: User,
        organization_id: uuid.UUID,
        payload: UserCreateRequest,
        *,
        public_base_url: str | None = None,
    ) -> User:
        self._authz.require_organization_admin(actor, organization_id)
        self._authz.require_role_assignable(actor, payload.role)

        user = User(
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role=payload.role,
            status=UserStatus.invited,
            organization_id=organization_id,
            # Пароль задаётся при принятии приглашения. Ставим случайный, а не
            # пустой/предсказуемый: иначе получится учётка со входом по known-хешу.
            password_hash=self._passwords.hash_password(secrets.token_urlsafe(32)),
            created_by=actor.id,
        )
        self._db.add(user)

        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с такой почтой уже существует",
            ) from exc

        await self._set_groups(user, payload.group_ids, organization_id)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            action="create",
            after={
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role,
                "status": user.status,
            },
        )
        await InvitationService(self._db).issue(
            user, invited_by=actor.id, public_base_url=public_base_url
        )
        return await self.get_user(organization_id, user.id)

    async def resend_invitation(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        public_base_url: str | None = None,
    ) -> User:
        user = await self.get_user(organization_id, user_id)
        self._authz.require_can_manage_user(actor, user)
        await InvitationService(self._db).issue(
            user,
            invited_by=actor.id,
            enforce_cooldown=True,
            public_base_url=public_base_url,
        )
        return user

    async def update_user(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: UserUpdateRequest,
        *,
        public_base_url: str | None = None,
    ) -> User:
        user = await self.get_user(organization_id, user_id)
        self._authz.require_can_manage_user(actor, user)

        before = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "status": user.status,
        }

        # Понижение роли или блокировка последнего админа обезглавит организацию.
        losing_admin = (
            payload.role is not None and payload.role != UserRole.admin
        ) or (
            payload.status is not None and payload.status != UserStatus.active
        )
        if losing_admin:
            await self._guard_last_admin(user)

        if payload.role is not None:
            self._authz.require_role_assignable(actor, payload.role)
            user.role = payload.role
        email_changed = payload.email is not None and payload.email != user.email
        if payload.email is not None:
            user.email = payload.email
        if payload.first_name is not None:
            user.first_name = payload.first_name
        if payload.last_name is not None:
            user.last_name = payload.last_name
        if payload.status is not None:
            user.status = payload.status
        user.updated_by = actor.id

        if payload.group_ids is not None:
            await self._set_groups(user, payload.group_ids, organization_id)

        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Пользователь с такой почтой уже существует",
            ) from exc

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            action="update",
            before=before,
            after={
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role,
                "status": user.status,
            },
        )
        if email_changed and user.status == UserStatus.invited:
            # Старая ссылка могла уйти прежнему владельцу адреса. Немедленно
            # заменяем токен и отправляем приглашение уже на новый email.
            await InvitationService(self._db).issue(
                user, invited_by=actor.id, public_base_url=public_base_url
            )
        else:
            await self._db.commit()
        return await self.get_user(organization_id, user_id)

    async def set_blocked(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        blocked: bool,
    ) -> User:
        user = await self.get_user(organization_id, user_id)
        self._authz.require_can_manage_user(actor, user)

        if blocked:
            await self._guard_last_admin(user)

        before = {"status": user.status}
        # Разблокировка возвращает в active даже из invited: админ явно
        # подтверждает, что пользователь работает.
        user.status = UserStatus.blocked if blocked else UserStatus.active
        user.updated_by = actor.id

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            action="block" if blocked else "unblock",
            before=before,
            after={"status": user.status},
        )
        await self._db.commit()
        return await self.get_user(organization_id, user_id)

    async def delete_user(
        self,
        actor: User,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        user = await self.get_user(organization_id, user_id)
        self._authz.require_can_manage_user(actor, user)

        if user.id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя удалить самого себя",
            )

        before = {
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "status": user.status,
        }

        # Гранты пользователя FK не держат (subject_id полиморфный) — БД их не
        # уберёт, убираем руками. Иначе останутся мусорные строки.
        await self._purge_grants(user.id, AccessSubjectType.user)

        self._audit.record(
            organization_id=organization_id,
            actor_user_id=actor.id,
            entity_type="user",
            entity_id=user.id,
            action="delete",
            before=before,
        )
        await self._db.delete(user)  # членство в группах уйдёт по FK CASCADE
        await self._db.commit()

    # ── вспомогательное ─────────────────────────────────────────────────────

    async def _purge_grants(
        self,
        subject_id: uuid.UUID,
        subject_type: AccessSubjectType,
    ) -> None:
        grants = (
            await self._db.execute(
                select(AccessGrant).where(
                    AccessGrant.subject_type == subject_type,
                    AccessGrant.subject_id == subject_id,
                )
            )
        ).scalars().all()
        for grant in grants:
            await self._db.delete(grant)

    async def _set_groups(
        self,
        user: User,
        group_ids: list[uuid.UUID],
        organization_id: uuid.UUID,
    ) -> None:
        """Заменяет набор групп пользователя.

        Чужие группы отсекаем явной проверкой: составной FK их тоже не пропустит,
        но 400 с внятным текстом лучше, чем IntegrityError из недр драйвера.
        """
        requested = set(group_ids)
        if requested:
            found = set(
                (
                    await self._db.execute(
                        select(UserGroup.id).where(
                            UserGroup.id.in_(requested),
                            UserGroup.organization_id == organization_id,
                        )
                    )
                ).scalars().all()
            )
            unknown = requested - found
            if unknown:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Указаны группы, которых нет в этой организации",
                )

        current = set(
            (
                await self._db.execute(
                    select(UserGroupMember.user_group_id).where(
                        UserGroupMember.user_id == user.id
                    )
                )
            ).scalars().all()
        )

        for group_id in requested - current:
            self._db.add(
                UserGroupMember(
                    user_group_id=group_id,
                    user_id=user.id,
                    organization_id=organization_id,
                )
            )
        for group_id in current - requested:
            member = await self._db.get(UserGroupMember, (group_id, user.id))
            if member is not None:
                await self._db.delete(member)

        await self._db.flush()

    async def count_accessible_communities(self, user: User) -> int:
        """Сколько сообществ доступно пользователю (колонка в таблице UI)."""
        ids = await self._authz.list_accessible_community_ids(
            user, PermissionEnum.view_community
        )
        if ids is None:
            # Админ/суперадмин — все сообщества организации.
            from backend.db.publics import Public

            return int(
                await self._db.scalar(
                    select(func.count())
                    .select_from(Public)
                    .where(Public.organization_id == user.organization_id)
                )
                or 0
            )
        return len(ids)
