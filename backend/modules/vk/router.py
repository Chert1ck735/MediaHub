"""FastAPI router VK-модуля."""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import async_session_maker, get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.store import JobKind, ProgressReporter, create_job, run_job_in_background
from backend.modules.vk.links.link_parser import VkLinkParser
from backend.modules.vk.repositories.ingestion_repository import VkIngestionRepository
from backend.modules.vk.schemas import CreatePostResponse, CreatePostRequest, ParsePostsRequest, ParsePostsResponse, \
    ParsedPost, VkDefaultPublicResponse, DeletePostRequest, DeletePostResponse, EditPostResponse, EditPostRequest, \
    IngestVkLinkRequest, IngestVkLinkResponse
from backend.modules.vk.services.ingestion_service import VkIngestionService
from backend.modules.vk.services.owner_resolver_service import VkOwnerResolverService
from backend.modules.vk.utils.api_client import VkApiError, VkApiClient
from backend.modules.vk.dto.dto import UploadPhotoDTO, EditVkPostDTO, CreateVkPostDTO
from backend.modules.vk.repositories.public_repository import VkPublicRepository
from backend.modules.vk.services.posting_service import VkPostingService
from backend.modules.vk.services.public_service import VkPublicService
from backend.modules.vk.services.wall_parser_service import VkWallParserService
from backend.modules.vk.utils.errors import VKAPIError, InvalidVKUrlError, IngestionError
from backend.modules.vk.utils.interfaces import VkIngestionServiceProtocol, VkPublicServiceProtocol, \
    VkPostingServiceProtocol, VkWallParserServiceProtocol

router = APIRouter(prefix="/api/vk", tags=["vk"])


def get_wall_parser_service() -> VkWallParserServiceProtocol:
    """Dependency factory сервиса чтения стены."""
    return VkWallParserService()


def get_posting_service() -> VkPostingServiceProtocol:
    """Dependency factory сервиса публикации."""
    return VkPostingService()


def get_public_service(db: AsyncSession = Depends(get_db)) -> VkPublicServiceProtocol:
    """Dependency factory сервиса дефолтного VK-паблика."""
    return VkPublicService(VkPublicRepository(db))


def _default_public_response(link) -> VkDefaultPublicResponse:
    """Маппит PublicSocialLink в HTTP response schema."""
    if not link:
        return VkDefaultPublicResponse(public_social_link_id=None, title=None, url=None, external_public_id=None)
    return VkDefaultPublicResponse(public_social_link_id=str(link.id), title=link.title, url=link.url, external_public_id=link.external_public_id)


@router.post("/parse", response_model=ParsePostsResponse)
def parse_wall(payload: ParsePostsRequest, parser_service: VkWallParserServiceProtocol = Depends(get_wall_parser_service)) -> ParsePostsResponse:
    """Парсит стену VK-сообщества."""
    try:
        result = parser_service.fetch_posts(url=payload.url, max_posts=payload.max_posts)
    except InvalidVKUrlError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (VKAPIError, VkApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    parsed = [parser_service.parse_post(post) for post in result.posts]
    return ParsePostsResponse(domain=result.domain_label, count=len(parsed), posts=[ParsedPost(**post.__dict__) for post in parsed])


@router.post("/poster", response_model=CreatePostResponse, status_code=status.HTTP_201_CREATED)
def create_post(payload: CreatePostRequest, _: User = Depends(get_current_user), posting_service: VkPostingServiceProtocol = Depends(get_posting_service)) -> CreatePostResponse:
    """Публикует пост в VK."""
    try:
        post_id = posting_service.create_post(CreateVkPostDTO(message=payload.message, attachments=payload.attachments, from_group=payload.from_group))
    except (VKAPIError, VkApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return CreatePostResponse(post_id=post_id, url=posting_service.post_url(post_id))


@router.post("/delete", response_model=DeletePostResponse)
def delete_post(payload: DeletePostRequest, _: User = Depends(get_current_user), posting_service: VkPostingServiceProtocol = Depends(get_posting_service)) -> DeletePostResponse:
    """Удаляет пост VK."""
    try:
        success = posting_service.delete_post(payload.post_id)
    except (VKAPIError, VkApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return DeletePostResponse(success=success)


@router.post("/edit", response_model=EditPostResponse)
def edit_post(payload: EditPostRequest, _: User = Depends(get_current_user), posting_service: VkPostingServiceProtocol = Depends(get_posting_service)) -> EditPostResponse:
    """Редактирует пост VK."""
    try:
        success = posting_service.edit_post(EditVkPostDTO(post_id=payload.post_id, message=payload.message, attachments=payload.attachments))
    except (VKAPIError, VkApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    if not success:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="VK вернул неуспешный результат редактирования")
    return EditPostResponse(post_id=payload.post_id, url=posting_service.post_url(payload.post_id))


@router.get("/default-public", response_model=VkDefaultPublicResponse)
async def get_default_public(user: User = Depends(get_current_user), public_service: VkPublicServiceProtocol = Depends(get_public_service)) -> VkDefaultPublicResponse:
    """Возвращает дефолтный VK-паблик для публикации."""
    link = await public_service.get_default_public(user)
    return _default_public_response(link)


@router.post("/ingest")
async def ingest_vk_link(payload: IngestVkLinkRequest, user: User = Depends(get_current_user)) -> dict[str, str]:
    """Запускает импорт из VK фоновой задачей и возвращает job_id для опроса."""
    job = await create_job(JobKind.vk_ingest, message="Preparing import...")

    async def runner(reporter: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            api_client = VkApiClient()
            ingestion_service: VkIngestionServiceProtocol = VkIngestionService(
                repository=VkIngestionRepository(session),
                api_client=api_client,
                link_parser=VkLinkParser(),
                owner_resolver=VkOwnerResolverService(api_client),
            )
            try:
                result = await ingestion_service.ingest_link(
                    user,
                    payload.url,
                    max_posts=payload.max_posts,
                    fetch_comments=payload.fetch_comments,
                    date_from=payload.date_from,
                    date_to=payload.date_to,
                    reporter=reporter,
                )
            except IngestionError as exc:
                raise RuntimeError(f"Import error: {exc}") from exc
            except (VKAPIError, VkApiError) as exc:
                raise RuntimeError(f"VK API: {exc}") from exc
            return IngestVkLinkResponse(
                type=result.type.value,
                canonical_url=result.canonical_url,
                public_id=result.public_id,
                public_social_link_id=result.public_social_link_id,
                posts_imported=result.posts_imported,
                publications_imported=result.publications_imported,
                comments_imported=result.comments_imported,
                notes=result.notes,
            ).model_dump()

    run_job_in_background(job, runner)
    return {"job_id": job.id}


@router.post("/upload-photo")
async def upload_photo(file: UploadFile = File(...), _: User = Depends(get_current_user), posting_service: VkPostingServiceProtocol = Depends(get_posting_service)) -> dict[str, str]:
    """Загружает фото в VK и возвращает attachment вида photo{owner}_{id}."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Нужен файл изображения")
    try:
        attachment = posting_service.upload_wall_photo(UploadPhotoDTO(file_bytes=await file.read(), filename=file.filename or "photo.jpg", content_type=file.content_type))
    except (VKAPIError, VkApiError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return {"attachment": attachment}
