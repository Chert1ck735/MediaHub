"""HTTP API Telegram-импорта."""

from fastapi import APIRouter, Depends

from backend.db.database import async_session_maker
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.store import ProgressReporter, create_job, run_job_in_background
from backend.modules.jobs.models import JobKind
from backend.modules.telegram.errors import TelegramConfigurationError, TelegramIngestionError
from backend.modules.telegram.schemas import IngestTelegramLinkRequest, IngestTelegramLinkResponse
from backend.modules.telegram.services.ingestion_service import TelegramIngestionService

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/ingest")
async def ingest_telegram_link(
    payload: IngestTelegramLinkRequest, user: User = Depends(get_current_user)
) -> dict[str, str]:
    """Запускает импорт Telegram в фоне, чтобы не держать HTTP-запрос открытым."""
    job = await create_job(JobKind.telegram_ingest, message="Подготовка импорта Telegram…")

    async def runner(reporter: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            service = TelegramIngestionService(session)
            try:
                result = await service.ingest_link(
                    user,
                    payload.url,
                    max_posts=payload.max_posts,
                    fetch_comments=payload.fetch_comments,
                    date_from=payload.date_from,
                    date_to=payload.date_to,
                    reporter=reporter,
                )
            except (TelegramConfigurationError, TelegramIngestionError, ValueError) as exc:
                raise RuntimeError(f"Ошибка импорта Telegram: {exc}") from exc
            return IngestTelegramLinkResponse(
                type=result.type,
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

