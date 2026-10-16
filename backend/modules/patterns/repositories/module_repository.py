"""Репозиторий patterns.

Здесь живут только SQL-запросы, нужные сценариям patterns.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.enums import PublicationStatusEnum
from backend.db.modules import Module
from backend.db.posts import Post
from backend.db.publics import Public


class ModuleRepository:
    """Отвечает за чтение и запись Public, Post и Module для сценария patterns."""

    def __init__(self, db: AsyncSession):
        """Сохраняет session, через которую выполняются запросы."""
        self.db = db

    async def get_public_by_name(self, organization_id: uuid.UUID, name: str) -> Public | None:
        """Ищет паблик организации по точному названию."""
        result = await self.db.execute(
            select(Public).where(
                Public.organization_id == organization_id,
                Public.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_recent_published_posts(self, public_id: uuid.UUID, limit: int = 30) -> list[Post]:
        """Возвращает последние опубликованные посты паблика для LLM-контекста."""
        result = await self.db.execute(
            select(Post)
            .where(
                Post.public_id == public_id,
                Post.status == PublicationStatusEnum.published,
            )
            .order_by(func.coalesce(Post.published_at, Post.created_at).desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_public_id(self, public_id: uuid.UUID) -> Module | None:
        """Ищет модуль, который уже привязан к паблику."""
        result = await self.db.execute(select(Module).where(Module.public_id == public_id))
        return result.scalar_one_or_none()

    async def list_by_organization(self, organization_id: uuid.UUID) -> list[Module]:
        """Возвращает модули организации от новых к старым."""
        result = await self.db.execute(
            select(Module)
            .join(Public, Public.id == Module.public_id)
            .where(Public.organization_id == organization_id)
            .order_by(Module.created_at.desc())
        )
        return list(result.scalars().all())

    async def add(self, module: Module) -> Module:
        """Добавляет модуль в текущую транзакцию."""
        self.db.add(module)
        return module

    async def commit(self) -> None:
        await self.db.commit()

    async def refresh(self, module: Module) -> None:
        await self.db.refresh(module)
