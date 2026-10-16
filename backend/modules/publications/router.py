from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.enums import PermissionEnum
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.organization.guards import require_link_permission
from backend.modules.posts.schema import PostResponse, PublicationCreateRequest, PublicationUpdateRequest
from backend.modules.posts.serializers import serialize_post
from backend.modules.publications import service

logger = get_logger(__name__)
router = APIRouter(tags=["publications"])


@router.post(
    "/api/posts/{post_id}/publications",
    response_model=PostResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_publication(
    post_id: str,
    payload: PublicationCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    logger.info(
        "Получен запрос на создание публикации",
        extra={
            "user_id": str(current_user.id),
            "post_id": post_id,
            "platform": payload.platform,
            "public_social_link_id": payload.public_social_link_id,
        },
    )

    # Публиковать в сообщество можно только с правом create_post. Проверка
    # именно здесь, на сервере: прямой POST в обход UI обязан получить 403.
    await require_link_permission(
        db,
        current_user,
        payload.public_social_link_id,
        PermissionEnum.create_post,
    )

    post = await service.create_publication(
        db,
        post_id,
        current_user,
        platform=payload.platform,
        public_social_link_id=payload.public_social_link_id,
        scheduled_at=payload.scheduled_at,
        status_value=payload.status,
        external_post_id=payload.external_post_id,
        url=payload.url,
        published_at=payload.published_at,
        error_message=payload.error_message,
    )

    logger.info(
        "Публикация успешно создана",
        extra={
            "user_id": str(current_user.id),
            "post_id": post_id,
            "platform": payload.platform,
        },
    )

    return serialize_post(post)

@router.patch("/api/publications/{publication_id}", response_model=PostResponse)
async def update_publication(
    publication_id: str,
    payload: PublicationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    logger.info(
        "Получен запрос на обновление публикации",
        extra={
            "user_id": str(current_user.id),
            "publication_id": publication_id,
            "platform": payload.platform,
        },
    )

    post = await service.update_publication(
        db,
        publication_id,
        current_user,
        platform=payload.platform,
        public_social_link_id=payload.public_social_link_id,
        scheduled_at=payload.scheduled_at,
        status_value=payload.status,
        external_post_id=payload.external_post_id,
        url=payload.url,
        published_at=payload.published_at,
        error_message=payload.error_message,
    )

    logger.info(
        "Публикация успешно обновлена",
        extra={
            "user_id": str(current_user.id),
            "publication_id": publication_id,
            "platform": payload.platform,
        },
    )

    return serialize_post(post)



@router.delete("/api/publications/{publication_id}", response_model=PostResponse)
async def delete_publication(
    publication_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    logger.info(
        "Получен запрос на удаление публикации",
        extra={
            "user_id": str(current_user.id),
            "publication_id": publication_id,
        },
    )

    post = await service.delete_publication(
        db,
        publication_id,
        current_user,
    )

    logger.info(
        "Публикация успешно удалена",
        extra={
            "user_id": str(current_user.id),
            "publication_id": publication_id,
        },
    )

    return serialize_post(post)
