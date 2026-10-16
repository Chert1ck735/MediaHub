from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.rate_limit import RateLimiter
from backend.db.database import get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.llm.repositories.public_module_repository import PublicModuleRepository
from backend.modules.llm.services.post_generation_service import PostGenerationService
from backend.modules.llm.services.public_module_context_service import (
    PublicModuleContextService,
)
from backend.modules.llm.services.usage_metrics_service import LLMUsageMetricsService


_llm_generate_limiter = RateLimiter(max_calls=10, window_seconds=60)


async def get_rate_limited_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Возвращает текущего пользователя после проверки лимита генерации языковой моделью."""

    await _llm_generate_limiter.check_async(
        key=str(current_user.id),
        route="llm.generate",
    )
    return current_user


def get_post_generation_service() -> PostGenerationService:
    return PostGenerationService()


def get_usage_metrics_service() -> LLMUsageMetricsService:
    return LLMUsageMetricsService()


def get_public_module_context_service(
    db: AsyncSession = Depends(get_db),
) -> PublicModuleContextService:
    return PublicModuleContextService(PublicModuleRepository(db))
