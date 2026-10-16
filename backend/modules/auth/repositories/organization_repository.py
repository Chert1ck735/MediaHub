"""Репозиторий для работы с организациями."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import Organization


class OrganizationRepository:
    """Отвечает только за операции с организациями в базе данных."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, organization: Organization) -> Organization:
        """Добавляет организацию в текущую транзакцию."""

        self.db.add(organization)
        await self.db.flush()
        return organization
