from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.logger_config import get_logger
from backend.db.database import get_db
from backend.db.users import User
from backend.modules.auth.deps import get_current_user
from backend.modules.report import service
from backend.modules.report.schema import (
    ReportGenerateRequest,
    ReportGenerateResponse,
    ReportPreviewRequest,
    ReportPreviewResponse,
)
from backend.modules.report.services.pdf_report_service import ReportPdfService
from backend.modules.report.services.preview_service import ReportPreviewService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/report", tags=["report"])


def _cleanup_file(path: str) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def _report_error(exc: service.ReportError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _unexpected_error(prefix: str, exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"{prefix}: {exc}",
    )


@router.post("/generate", response_model=ReportGenerateResponse)
def generate_report(
    payload: ReportGenerateRequest,
    current_user: User = Depends(get_current_user),
) -> ReportGenerateResponse:
    logger.info(
        "Report generation requested",
        extra={
            "platform": payload.platform,
            "csv_path": payload.csv_path,
            "output_path": payload.output_path,
        },
    )

    try:
        output = service.generate_report(
            platform=payload.platform,
            csv_path=payload.csv_path,
            output_path=payload.output_path,
        )
    except service.ReportError as exc:
        logger.error("Report generation rejected", extra={"platform": payload.platform, "error": str(exc)})
        raise _report_error(exc) from exc
    except Exception as exc:
        logger.exception("Report generation failed", extra={"platform": payload.platform, "error": str(exc)})
        raise _unexpected_error("Ошибка генерации отчёта", exc) from exc

    logger.info("Report generated", extra={"platform": payload.platform, "output_path": output})
    return ReportGenerateResponse(platform=payload.platform, output_path=output)


@router.post("/preview", response_model=ReportPreviewResponse)
async def preview_report(
    payload: ReportPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportPreviewResponse:
    logger.info(
        "Report preview requested",
        extra={
            "user_id": str(current_user.id),
            "platform": payload.platform,
            "period": payload.period,
            "public_social_link_id": payload.public_social_link_id,
        },
    )

    try:
        result = await ReportPreviewService(db).preview(current_user, payload)
    except service.ReportError as exc:
        logger.error(
            "Report preview rejected",
            extra={"user_id": str(current_user.id), "platform": payload.platform, "error": str(exc)},
        )
        raise _report_error(exc) from exc
    except Exception as exc:
        logger.exception(
            "Report preview failed",
            extra={"user_id": str(current_user.id), "platform": payload.platform, "error": str(exc)},
        )
        raise _unexpected_error("Ошибка превью отчёта", exc) from exc

    logger.info(
        "Report preview built",
        extra={
            "user_id": str(current_user.id),
            "platform": result.platform,
            "posts_count": len(result.all_posts),
            "top_posts_count": len(result.top_posts),
        },
    )
    return result


@router.post("/recommendations")
async def report_recommendations(
    payload: ReportPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """LLM-рекомендации по контенту (lazy, кэшируются) — грузятся отдельно от превью."""
    try:
        text = await ReportPreviewService(db).recommendations(current_user, payload)
    except service.ReportError as exc:
        raise _report_error(exc) from exc
    except Exception as exc:
        logger.exception("Report recommendations failed", extra={"user_id": str(current_user.id)})
        raise _unexpected_error("Ошибка генерации рекомендаций", exc) from exc
    return {"recommendations": text}


@router.post("/pdf")
async def download_pdf(
    payload: ReportGenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    logger.info(
        "PDF report requested",
        extra={
            "user_id": str(current_user.id),
            "platform": payload.platform,
            "period": payload.period,
        },
    )

    try:
        result = await ReportPdfService(db).generate(current_user, payload)
    except service.ReportError as exc:
        logger.error(
            "PDF report rejected",
            extra={"user_id": str(current_user.id), "platform": payload.platform, "error": str(exc)},
        )
        raise _report_error(exc) from exc
    except Exception as exc:
        logger.exception(
            "PDF report failed",
            extra={"user_id": str(current_user.id), "platform": payload.platform, "error": str(exc)},
        )
        raise _unexpected_error("Ошибка генерации PDF", exc) from exc

    logger.info(
        "PDF report generated",
        extra={"user_id": str(current_user.id), "pdf_path": result.path},
    )
    background_tasks.add_task(_cleanup_file, result.path)
    return FileResponse(
        path=result.path,
        media_type="application/pdf",
        filename=Path(result.path).name,
    )
