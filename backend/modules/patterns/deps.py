from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_db
from backend.modules.patterns.services.module_service import ModuleService


def get_module_service(
    db: AsyncSession = Depends(get_db),
) -> ModuleService:
    return ModuleService(db)
