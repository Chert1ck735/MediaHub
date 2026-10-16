"""Репозиторий для работы с пользователями."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User


class UserRepository:
    """Отвечает только за операции с пользователями в базе данных."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_email(self, email: str) -> User | None:
        """Возвращает пользователя по email."""

        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def get_by_id(self, user_id: str) -> User | None:
        """Возвращает пользователя по UUID."""

        result = await self.db.execute(select(User).where(User.id == uuid.UUID(user_id)))
        return result.scalar_one_or_none()

    async def add(self, user: User) -> User:
        """Добавляет пользователя в текущую транзакцию."""

        self.db.add(user)
        return user
