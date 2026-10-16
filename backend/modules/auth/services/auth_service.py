"""Бизнес-логика авторизации и регистрации."""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User, Organization, OrgType, UserRole, UserStatus
from backend.modules.auth.repositories.organization_repository import OrganizationRepository
from backend.modules.auth.repositories.user_repository import UserRepository
from backend.modules.auth.services.password_service import PasswordService
from backend.modules.auth.services.token_service import TokenService
from backend.modules.auth.services.verification_service import VerificationService


class AuthService:
    """Сервис авторизации, объединяющий регистрацию, вход и получение пользователя."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.users = UserRepository(db)
        self.organizations = OrganizationRepository(db)
        self.passwords = PasswordService()
        self.tokens = TokenService()
        self.verification = VerificationService(db)

    @staticmethod
    def _split_name(name: str) -> tuple[str, str]:
        """Режет ФИО одной строкой на имя и фамилию по первому пробелу.

        Публичная регистрация принимает одно поле «имя», а модель хранит
        first_name/last_name. Фамилии может не быть — пустая строка честнее
        выдуманной.
        """
        parts = name.strip().split(None, 1)
        if not parts:
            return "Пользователь", ""
        return parts[0], (parts[1].strip() if len(parts) > 1 else "")

    async def register(self, email: str, name: str, password: str) -> tuple[User, str]:
        """
        Регистрирует пользователя. Почта обязана быть подтверждена кодом.

        Возвращает пользователя и access-токен.
        """

        # БД требует email в lowercase (ck_users_email_lowercase): нормализуем
        # здесь, иначе регистрация с заглавными буквами упадёт на констрейнте.
        email = email.strip().lower()

        existing_user = await self.users.get_by_email(email)

        if existing_user:
            # РАНЬШЕ здесь молча перезаписывался пароль существующего
            # пользователя и выдавался токен — то есть «регистрация» на чужую
            # почту была захватом чужого аккаунта. Теперь — отказ.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Эта почта уже зарегистрирована",
            )

        # Главная проверка: без подтверждённого кода из письма регистрации нет.
        # Стоит ДО любых записей, и гасит подтверждение (оно одноразовое).
        await self.verification.consume_verified(email)

        organization = Organization(
            name=f"Организация {name}",
            type=OrgType.other,
        )

        await self.organizations.add(organization)

        first_name, last_name = self._split_name(name)

        # Первый пользователь новой организации — её админ.
        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=self.passwords.hash_password(password),
            role=UserRole.admin,
            organization_id=organization.id,
        )

        await self.users.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        token = self.tokens.create_access_token(str(user.id), user.email)

        return user, token

    async def authenticate(self, email: str, password: str) -> tuple[User, str] | None:
        """
        Проверяет email и пароль пользователя.
        Возвращает пользователя и access-токен, если данные корректны.
        """

        user = await self.users.get_by_email(email.strip().lower())

        if not user or user.status != UserStatus.active:
            return None

        if not self.passwords.verify_password(password, user.password_hash):
            return None

        token = self.tokens.create_access_token(str(user.id), user.email)

        return user, token

    async def get_user_by_id(self, user_id: str) -> User | None:
        """Возвращает пользователя по ID."""

        return await self.users.get_by_id(user_id)

    async def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not self.passwords.verify_password(current_password, user.password_hash):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Текущий пароль указан неверно",
            )
        user.password_hash = self.passwords.hash_password(new_password)
        await self.db.commit()

    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        """Ставит новый пароль по коду из письма.

        Пользователя ищем ПОСЛЕ проверки кода: иначе ответ отличался бы для
        существующих и несуществующих адресов.
        """
        email = email.strip().lower()

        await self.verification.consume_code(email, code)

        user = await self.users.get_by_email(email)
        if user is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Не удалось сменить пароль. Запросите код заново.",
            )

        user.password_hash = self.passwords.hash_password(new_password)
        await self.db.commit()
