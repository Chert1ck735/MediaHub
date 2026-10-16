import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.logger_config import get_logger
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.llm.clients import LLMError
from backend.modules.llm.deps import (
    get_post_generation_service,
    get_public_module_context_service,
    get_rate_limited_user,
    get_usage_metrics_service,
)
from backend.modules.llm.repositories.public_module_repository import (
    InvalidPublicSocialLinkId,
    PublicSocialLinkNotFound,
)
from backend.modules.llm.schemas import GeneratePostRequest, GeneratePostResponse
from backend.modules.llm.services.post_generation_service import PostGenerationService
from backend.modules.llm.services.public_module_context_service import (
    PublicModuleContextService,
)
from backend.modules.llm.services.usage_metrics_service import LLMUsageMetricsService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.post("/generate", response_model=GeneratePostResponse)
async def generate_post(
    payload: GeneratePostRequest,
    current_user: User = Depends(get_rate_limited_user),
    post_generation_service: PostGenerationService = Depends(
        get_post_generation_service
    ),
    module_context_service: PublicModuleContextService = Depends(
        get_public_module_context_service
    ),
) -> GeneratePostResponse:
    """Генерирует варианты текста поста для авторизованного пользователя."""

    logger.info(
        "LLM post generation requested",
        extra={
            "user_id": str(current_user.id),
            "post_type": getattr(payload, "post_type", None),
            "public_social_link_id": payload.public_social_link_id,
        },
    )

    selected_modules, public_context = await _load_generation_context(
        module_context_service,
        current_user,
        payload,
    )

    try:
        result = await asyncio.to_thread(
            post_generation_service.generate,
            payload,
            organization_modules=selected_modules,
            public_context=public_context,
        )
    except LLMError as exc:
        logger.error(
            "LLM post generation failed",
            extra={
                "user_id": str(current_user.id),
                "error": str(exc),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM сервис недоступен или вернул некорректный ответ",
        ) from exc

    logger.info(
        "LLM post generated",
        extra={
            "user_id": str(current_user.id),
            "model": result.model,
        },
    )

    return GeneratePostResponse(
        text=result.text,
        model=result.model,
    )


async def _load_generation_context(
    module_context_service: PublicModuleContextService,
    current_user: User,
    payload: GeneratePostRequest,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Читает выбранный паблик и, если он есть, модуль организации."""

    try:
        public_context = await module_context_service.get_generation_context(
            public_social_link_id=payload.public_social_link_id,
            organization_id=current_user.organization_id,
        )
        selected_modules = await module_context_service.list_for_generation(
            public_social_link_id=payload.public_social_link_id,
            organization_id=current_user.organization_id,
        )
        return selected_modules, public_context
    except InvalidPublicSocialLinkId as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid public_social_link_id",
        ) from exc
    except PublicSocialLinkNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected public was not found for current organization",
        ) from exc


@router.get("/usage")
async def get_usage_metrics(
    limit: int = Query(50, ge=1, le=500),
    since_hours: int = Query(24, ge=1, le=24 * 90),
    current_user: User = Depends(get_current_user),
    usage_metrics_service: LLMUsageMetricsService = Depends(get_usage_metrics_service),
) -> dict[str, Any]:
    """Возвращает агрегированные метрики использования языковой модели за выбранное окно."""

    logger.info(
        "LLM usage metrics requested",
        extra={
            "user_id": str(current_user.id),
            "limit": limit,
            "since_hours": since_hours,
        },
    )

    report = usage_metrics_service.build_report(
        limit=limit,
        since_hours=since_hours,
    )

    logger.info(
        "LLM usage metrics built",
        extra={
            "user_id": str(current_user.id),
            "limit": limit,
            "since_hours": since_hours,
        },
    )

    return report
