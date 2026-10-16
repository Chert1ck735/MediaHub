"""HTTP-слой posts.

Файл принимает запросы, вызывает PostService и возвращает PostResponse.
SQL, сериализация и работа с текстом вынесены в отдельные модули.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.posts.schema import PostResponse, PostCreateRequest, PostUpdateVkRequest, PostUpdateRequest
from backend.modules.posts.utils.errors import PostError
from backend.modules.posts.serializers import serialize_post
from backend.modules.posts.service import PostService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/posts", tags=["posts"])


def _post_service(db: AsyncSession) -> PostService:
    """Фабрика держит обработчики тонкими, как в модуле auth."""
    return PostService(db)


def _bad_request(exc: PostError) -> HTTPException:
    """Преобразует доменную ошибку posts в ответ 400."""
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _post_not_found() -> HTTPException:
    """Создает единый ответ 404 для случаев, когда пост недоступен."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")


@router.get("/", response_model=list[PostResponse])
async def list_posts(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PostResponse]:
    """Возвращает список постов редактора для текущей организации."""
    logger.info(
        "Posts list requested",
        extra={"user_id": str(current_user.id), "endpoint": "GET /api/posts/"},
    )

    try:
        posts = await _post_service(db).list_posts(current_user)
    except PostError as exc:
        logger.warning("Posts list rejected", extra={"user_id": str(current_user.id), "error": str(exc)})
        raise _bad_request(exc) from exc

    logger.info(
        "Posts list built",
        extra={"user_id": str(current_user.id), "posts_count": len(posts)},
    )
    return [serialize_post(post) for post in posts]


@router.post("/", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Создает новый пост через редактор."""
    logger.info(
        "Post create requested",
        extra={"user_id": str(current_user.id), "title": payload.title, "strategy_id": payload.strategy_id},
    )

    try:
        post = await _post_service(db).create_post(
            current_user,
            title=payload.title,
            text_draft=payload.text_draft,
            text_generated=payload.text_generated,
            tone=payload.tone,
            vk_post_id=payload.vk_post_id,
            strategy_id=payload.strategy_id,
        )
    except PostError as exc:
        logger.warning("Post create rejected", extra={"user_id": str(current_user.id), "error": str(exc)})
        raise _bad_request(exc) from exc

    logger.info(
        "Post created",
        extra={"user_id": str(current_user.id), "post_id": str(post.id), "title": post.title},
    )
    return serialize_post(post)


@router.patch("/{post_id}/vk", response_model=PostResponse)
async def update_post_vk(
    post_id: str,
    payload: PostUpdateVkRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Обновляет VK-статус поста."""
    logger.info(
        "Post VK update requested",
        extra={"user_id": str(current_user.id), "post_id": post_id, "vk_post_id": payload.vk_post_id},
    )

    try:
        post = await _post_service(db).update_post_vk(post_id, current_user, payload.vk_post_id)
    except PostError as exc:
        raise _bad_request(exc) from exc

    if not post:
        raise _post_not_found()

    logger.info(
        "Post VK updated",
        extra={"user_id": str(current_user.id), "post_id": str(post.id), "vk_post_id": payload.vk_post_id},
    )
    return serialize_post(post)


@router.patch("/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: str,
    payload: PostUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PostResponse:
    """Обновляет редактируемые поля поста."""
    logger.info(
        "Post update requested",
        extra={"user_id": str(current_user.id), "post_id": post_id, "title": payload.title},
    )

    try:
        post = await _post_service(db).update_post(
            post_id,
            current_user,
            title=payload.title,
            text_draft=payload.text_draft,
            text_generated=payload.text_generated,
            tone=payload.tone,
            strategy_id=payload.strategy_id,
        )
    except PostError as exc:
        raise _bad_request(exc) from exc

    if not post:
        raise _post_not_found()

    logger.info(
        "Post updated",
        extra={"user_id": str(current_user.id), "post_id": str(post.id)},
    )
    return serialize_post(post)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Удаляет пост текущей организации."""
    logger.info(
        "Post delete requested",
        extra={"user_id": str(current_user.id), "post_id": post_id},
    )

    try:
        deleted = await _post_service(db).delete_post(post_id, current_user)
    except PostError as exc:
        raise _bad_request(exc) from exc

    if not deleted:
        raise _post_not_found()

    logger.info(
        "Post deleted",
        extra={"user_id": str(current_user.id), "post_id": post_id},
    )

