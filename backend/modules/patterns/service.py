"""Compatibility facade for patterns business use cases."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.modules import Module
from backend.db.users import User
from backend.modules.patterns.services.module_service import ModuleService


async def create_or_update_module(
    db: AsyncSession,
    user: User,
    *,
    name: str,
    goal: str | None,
    description: str | None,
) -> tuple[Module, bool]:
    return await ModuleService(db).create_or_update_module(
        user,
        name=name,
        goal=goal,
        description=description,
    )


async def list_modules(db: AsyncSession, user: User) -> list[Module]:
    return await ModuleService(db).list_modules(user)


__all__ = ["ModuleService", "create_or_update_module", "list_modules"]
