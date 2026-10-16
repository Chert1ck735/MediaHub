"""FastAPI router OK-модуля."""

from fastapi import APIRouter, Depends, HTTPException, status

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.store import JobKind, ProgressReporter, create_job, run_job_in_background
from backend.modules.ok.dto.dto import OkLinkType
from backend.modules.ok.links.link_parser import OkLinkParser
from backend.modules.ok.repositories.ingestion_repository import OkIngestionRepository
from backend.modules.ok.schemas import (
    IngestOkLinkRequest,
    IngestOkLinkResponse,
    ResolveOkLinkResponse,
)
from backend.modules.ok.services.ingestion_service import OkIngestionService
from backend.modules.ok.services.owner_resolver_service import OkOwnerResolverService
from backend.modules.ok.utils.api_client import OkApiClient
from backend.modules.ok.utils.errors import InvalidOkLinkError, OkApiError, OkIngestionError
from backend.modules.ok.utils.interfaces import OkIngestionServiceProtocol

router = APIRouter(prefix="/api/ok", tags=["ok"])


@router.post("/resolve", response_model=ResolveOkLinkResponse)
def resolve_ok_link(payload: IngestOkLinkRequest) -> ResolveOkLinkResponse:
    """Разбирает OK-ссылку локально, без обращения к OK API."""

    try:
        ref = OkLinkParser().parse(payload.url)
    except InvalidOkLinkError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ResolveOkLinkResponse(
        type=ref.type.value,
        canonical_url=ref.canonical_url,
        group_ref=ref.group_ref,
        topic_id=ref.topic_id,
        profile_ref=ref.profile_ref,
        supported=ref.type is not OkLinkType.PROFILE,
    )


@router.post("/ingest")
async def ingest_ok_link(
    payload: IngestOkLinkRequest,
    user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Запускает импорт OK как фоновую задачу и возвращает job_id для поллинга."""

    job = await create_job(JobKind.ok_ingest, message="Подготовка импорта…")

    async def runner(reporter: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            api_client = OkApiClient()
            ingestion_service: OkIngestionServiceProtocol = OkIngestionService(
                repository=OkIngestionRepository(session),
                api_client=api_client,
                link_parser=OkLinkParser(),
                owner_resolver=OkOwnerResolverService(api_client),
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
            except OkIngestionError as exc:
                raise RuntimeError(f"Ошибка импорта: {exc}") from exc
            except OkApiError as exc:
                raise RuntimeError(f"OK API: {exc}") from exc
            return IngestOkLinkResponse(
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
