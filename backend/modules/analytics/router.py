import io
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.logger_config import get_logger
from backend.db.database import get_db, async_session_maker
from backend.db.enums import PermissionEnum, UserRole
from backend.modules.organization.guards import accessible_community_ids
from backend.db import Comment, CommentAnalysis, Organization, Public, Publication, PublicSocialLink, Region, SocialNetwork
from backend.db.users import User
from backend.modules.analytics import classification, llm_coordination, llm_health
from backend.modules.analytics.repositories.public_query_repository import PublicQueryRepository
from backend.modules.analytics.schemas import PainCommentsPage, PainDetailResponse, PainEventLink, PainTrendItem, \
    PublicationPainBucket, StrategyRegenerateResponse, DeleteImportedPublicResponse, PainListItemResponse, \
    AnalyticsSummaryResponse, RebuildNeededResponse, AnalyticsRebuildResponse, AnalyticsImportResponse, \
    AnalyticsNormalizeRequest, AnalyticsNormalizeResponse, ReclassifyResponse, ReclassifyRequest, ClassifyBatchResponse, \
    PainMapPoint, GeoCacheStatus, GeoCacheRotateResponse, GeoKeysRequest, CaseComment, CaseCommentsRequest, Alert, Incident, AgencyStat, \
    ClassificationReviewPage, ClassificationReviewResolveRequest, ClassificationReviewTaxonomy, RegionOption, \
    PublicRegionUpdateRequest, PublicRegionResponse, AddressCaseGeocodingStats, \
    AddressCaseGeocodingBackfillResponse, AddressCaseDeleteRequest, AddressCaseDeleteResponse, \
    PublicLocationInferenceResponse

from backend.modules.analytics.constants import CATEGORY_ALIASES, SUBCATEGORY_ALIASES
from backend.modules.analytics.services.analytics_refresh_service import AnalyticsRefreshService
from backend.modules.analytics.services.appeal_daily_service import AppealDailyService
from backend.modules.analytics.services.imported_public_delete_service import ImportedPublicDeleteService
from backend.modules.analytics.services.pain_comments_service import PainCommentsService
from backend.modules.analytics.services.pain_detail_service import PainDetailService
from backend.modules.analytics.services.pain_events_service import PainEventsService
from backend.modules.analytics.services.pain_list_service import PainListService
from backend.modules.analytics.services.pain_strategy_service import PainStrategyRegenerationService
from backend.modules.analytics.services.pain_trends_service import PainTrendsService
from backend.modules.analytics.services.payload_import_service import PayloadImportService, PayloadNormalizeService
from backend.modules.analytics.services.public_query_service import PublicQueryService
from backend.modules.analytics.services.publication_pain_breakdown_service import PublicationPainBreakdownService
from backend.modules.analytics.services.public_location_inference_service import PublicLocationInferenceService
from backend.modules.analytics.services.rebuild_needed_service import RebuildNeededService
from backend.modules.analytics.services.summary_service import AnalyticsSummaryService
from backend.modules.analytics.services.quality_report_service import build_quality_report
from backend.app.runtime_settings import get_yandex_geocoder_keys, set_yandex_geocoder_keys
from backend.modules.analytics.utils.geo_keys import set_runtime_keys, usage as key_usage
from backend.modules.analytics.services.pain_map_service import PainMapService
from backend.modules.analytics.services.alerts_service import AlertsService
from backend.modules.analytics.services.incidents_service import IncidentsService
from backend.modules.analytics.services.agency_ranking_service import AgencyRankingService
from backend.modules.analytics.services.vk_snapshot_builder import VkSnapshotBuilder
from backend.modules.analytics.utils.time_helpers import period_to_since
from backend.modules.analytics.utils.public_link_filter import (
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)
from backend.modules.analytics.utils.municipality_filter import canonicalize_municipality_filters
from backend.app.slow_requests import snapshot as slow_requests_snapshot
from backend.modules.auth.deps import get_current_user
from backend.modules.jobs.models import JobKind
from backend.modules.jobs.store import create_job, ProgressReporter, run_job_in_background
from backend.modules.organization.municipalities import (
    canonical_municipality_name,
    is_krasnoyarsk_region_name,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _require_geo_cache_admin(user: User) -> None:
    role = getattr(user.role, "value", user.role)
    if role not in {UserRole.admin.value, UserRole.superadmin.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Диагностика geo-cache доступна только администраторам",
        )


def _require_public_settings_admin(user: User) -> None:
    role = getattr(user.role, "value", user.role)
    if role not in {UserRole.admin.value, UserRole.superadmin.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Настройки площадок доступны только администраторам",
        )


def _require_superadmin(user: User) -> None:
    role = getattr(user.role, "value", user.role)
    if role != UserRole.superadmin.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Действие доступно только суперадминистратору",
        )


def _municipality_filter(value: str | None) -> str | None:
    try:
        return ",".join(canonicalize_municipality_filters(value)) or None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _enum_value(value):
    return getattr(value, "value", value)


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _json_cell(value) -> str:
    if value in (None, ""):
        return ""
    return json.dumps(value, ensure_ascii=False, default=str)


def _excel_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        value = _json_cell(value)
    else:
        value = str(_enum_value(value))
    # Excel refuses strings longer than 32767 chars.
    return value[:32767]


def _dt_start(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _dt_end_exclusive(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)


@router.post("/classify-pending", response_model=ClassifyBatchResponse)
async def classify_pending_batch(
    limit: int = Query(50, ge=1, le=500),
    concurrency: int = Query(4, ge=1, le=16),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClassifyBatchResponse:
    """Прогоняет один батч pending-комментариев через классификацию."""

    stats = await classification.process_pending_batch(
        db,
        limit=limit,
        organization_id=current_user.organization_id,
        concurrency=concurrency,
    )
    return ClassifyBatchResponse(**stats.to_dict())


@router.post("/reclassify-vk", response_model=ReclassifyResponse)
async def reclassify_vk(
    payload: ReclassifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReclassifyResponse:
    """Возвращает группу comment_analysis в очередь на повторную классификацию."""

    try:
        requested = await classification.mark_organization_for_reclassify(
            db,
            current_user.organization_id,
            scope=payload.scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    return ReclassifyResponse(requeued=requested)


@router.post("/normalize-export", response_model=AnalyticsNormalizeResponse)
async def normalize_export(
    payload: AnalyticsNormalizeRequest,
    current_user: User = Depends(get_current_user),
) -> AnalyticsNormalizeResponse:
    """Нормализует внешний payload аналитики."""
    return PayloadNormalizeService().normalize(payload.source_name, payload.payload)


@router.post(
    "/import/global-problem",
    response_model=AnalyticsImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_global_problem(
    payload: AnalyticsNormalizeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsImportResponse:
    """Импортирует внешний payload в AnalysisSnapshot."""

    return await PayloadImportService(db).import_global_problem(
        current_user,
        payload.source_name,
        payload.payload,
    )


@router.get("/vk-comment-count")
async def vk_comment_count(
    period: str | None = Query(None),
    public_social_link_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Сколько VK-комментариев попадёт в классификацию (период + площадка)."""
    since = period_to_since(period)
    try:
        link_ids = parse_public_social_link_ids(public_social_link_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    count = await VkSnapshotBuilder(db).count_comment_rows(
        current_user,
        since,
        compact_public_social_link_filter(link_ids),
    )
    return {"count": count, "period": period}


@router.get("/classification/queue")
async def classification_queue(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Состояние очереди фоновой классификации (по организации юзера) — для индикатора в UI."""
    org_id = current_user.organization_id
    counts = await classification.count_classification_states(db, organization_id=org_id)
    by_public = await classification.count_queue_by_public(db, organization_id=org_id)
    review_count = await classification.count_manual_review(db, organization_id=org_id)
    pending = counts.get("pending", 0)
    processing = counts.get("processing", 0)
    failed_retrying = counts.get("failed_retrying", 0)
    remaining = pending + processing + failed_retrying
    performance = await classification.estimate_queue_performance(
        db,
        organization_id=org_id,
        remaining=remaining,
        failed_retrying=failed_retrying,
    )
    return {
        "pending": pending,
        "processing": processing,
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "failed_retrying": failed_retrying,
        "failed_final": counts.get("failed", 0) - failed_retrying,
        "needs_review": review_count,
        "in_progress": pending + processing,
        "remaining": remaining,
        **performance.to_dict(),
        "paused": llm_coordination.is_worker_paused(),
        "llm_ok": await llm_health.llm_reachable(),
        "by_public": by_public,
    }


@router.get("/classification/review/taxonomy", response_model=ClassificationReviewTaxonomy)
async def classification_review_taxonomy(
    current_user: User = Depends(get_current_user),
) -> ClassificationReviewTaxonomy:
    """Каноничная таксономия для ручной доводки LLM-классификации."""

    return ClassificationReviewTaxonomy(
        categories=list(CATEGORY_ALIASES.keys()),
        subcategories={
            category: list(items.keys())
            for category, items in SUBCATEGORY_ALIASES.items()
        },
    )


@router.get("/classification/review", response_model=ClassificationReviewPage)
async def classification_review(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ClassificationReviewPage:
    """Комментарии, где LLM закончила классификацию, но не выбрала категорию."""

    total, items = await classification.list_manual_review(
        db,
        organization_id=current_user.organization_id,
        limit=limit,
        offset=offset,
    )
    return ClassificationReviewPage(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@router.post("/classification/review/{analysis_id}/resolve")
async def resolve_classification_review(
    analysis_id: str,
    payload: ClassificationReviewResolveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Назначает категорию вручную и выводит комментарий из списка review."""

    category = payload.category.strip()
    subcategory = payload.subcategory.strip()
    if category not in CATEGORY_ALIASES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неизвестная категория")
    allowed_subcategories = SUBCATEGORY_ALIASES.get(category, {})
    if subcategory and subcategory not in allowed_subcategories:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неизвестная подкатегория")
    try:
        aid = uuid.UUID(analysis_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный analysis_id") from exc
    resolved = await classification.resolve_manual_review(
        db,
        aid,
        organization_id=current_user.organization_id,
        category=category,
        subcategory=subcategory,
        case_name=payload.case,
    )
    if not resolved:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Комментарий не найден в очереди проверки")
    return {"resolved": True}


@router.post("/classification/queue/public/{public_id}/skip")
async def skip_public_classification(
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Убирает комментарии паблика из очереди классификации (не удаляя данные)."""
    try:
        pid = uuid.UUID(public_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_id") from exc
    removed = await classification.skip_public_queue(
        db, pid, organization_id=current_user.organization_id
    )
    return {"removed": removed}


@router.post("/classification/worker/pause")
async def pause_classification_worker(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Поставить фоновый воркер классификации на паузу (вручную из UI)."""
    llm_coordination.pause_worker()
    return {"paused": True}


@router.post("/classification/worker/resume")
async def resume_classification_worker(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Снять фоновый воркер классификации с паузы."""
    llm_coordination.resume_worker()
    return {"paused": False}


@router.post("/rebuild-vk")
async def rebuild_vk_snapshot(
    force_reclassify: bool = Query(False),
    incremental: bool = Query(False),
    period: str | None = Query(None),
    prefilter: bool = Query(False),
    public_social_link_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Запускает rebuild VK-аналитики как background job."""
    since = period_to_since(period)
    try:
        public_social_link_ids = parse_public_social_link_ids(public_social_link_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    link_filter = compact_public_social_link_filter(public_social_link_ids)
    logger.info(
        "VK rebuild snapshot requested | user_id=%s | force_reclassify=%s | incremental=%s | period=%s | prefilter=%s | public_social_link_id=%s",
        current_user.id,
        force_reclassify,
        incremental,
        period,
        prefilter,
        public_social_link_id,
    )

    job = await create_job(JobKind.analytics_rebuild, message="Подготовка пересборки…")

    async def runner(progress: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            snapshot, stats = await AnalyticsRefreshService(session).refresh(
                current_user,
                force_reclassify=force_reclassify,
                incremental=incremental,
                since=since,
                prefilter=prefilter,
                public_social_link_id=link_filter,
                progress=progress,
            )
            return AnalyticsRebuildResponse(
                snapshot_id=str(snapshot.id),
                generated_at=snapshot.generated_at.isoformat(),
                pain_count=len(snapshot.raw_payload.get("pains", [])) if snapshot.raw_payload else 0,
                reclassified_comments=int(stats.get("reclassified_comments", 0)),
                llm_classified_comments=int(stats.get("llm_classified_comments", 0)),
                fallback_classified_comments=int(stats.get("fallback_classified_comments", 0)),
                elapsed_seconds=float(stats.get("elapsed_seconds", 0.0)),
                comments_per_min=int(stats.get("comments_per_min", 0)),
                prefilter_used=bool(stats.get("prefilter_used", False)),
                prefilter_dropped=int(stats.get("prefilter_dropped", 0)),
            ).model_dump()

    run_job_in_background(job, runner)
    return {"job_id": job.id}


@router.get("/rebuild-needed", response_model=RebuildNeededResponse)
async def rebuild_needed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RebuildNeededResponse:
    """Проверяет, нужно ли пересобирать VK snapshot."""

    return await RebuildNeededService(db).check(current_user)


@router.get("/summary", response_model=AnalyticsSummaryResponse)
async def get_summary(
    period: str = "all",
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsSummaryResponse:
    """Возвращает сводку аналитики."""

    try:
        return await AnalyticsSummaryService(db).get_summary(
            current_user,
            period=period,
            public_social_link_id=public_social_link_id,
            municipality_name=_municipality_filter(municipality_name),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (TypeError, AttributeError):
        raise
    except Exception as exc:
        if "badly formed hexadecimal UUID" in str(exc) or "invalid literal" in str(exc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
        raise


@router.get("/appeals/daily")
async def appeals_daily(
    since: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Обращения по дням и площадкам. Только счётчики, без текстов и авторов."""
    try:
        since_date = date.fromisoformat(since)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since ожидается в формате YYYY-MM-DD",
        ) from exc

    return await AppealDailyService(db).daily_counts(current_user, since_date)


@router.get("/pains", response_model=list[PainListItemResponse])
async def list_pains(
    period: str = "all",
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PainListItemResponse]:
    """Возвращает список болей (с учётом периода и выбранной площадки)."""

    try:
        return await PainListService(db).list_pains(
            current_user,
            period=period,
            public_social_link_id=public_social_link_id,
            municipality_name=_municipality_filter(municipality_name),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/pain-map", response_model=list[PainMapPoint])
async def pain_map(
    period: str = "all",
    public_social_link_id: str | None = None,
    problem_type: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PainMapPoint]:
    """Точки карты болей: адресные кейсы с координатами и весом (упоминаниями)."""

    try:
        links = parse_public_social_link_ids(public_social_link_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    service = PainMapService(db)
    link_slices = links or [None]
    merged: dict[tuple, dict] = {}
    municipality = _municipality_filter(municipality_name)
    for link in link_slices:
        points = await service.points(
            current_user,
            since=period_to_since(period),
            link_id=link,
            problem_type=(problem_type or "").strip() or None,
            municipality_name=municipality,
        )
        for point in points:
            key = (point["name"], point["lat"], point["lon"])
            current = merged.setdefault(key, {**point, "count": 0, "cases": []})
            current["count"] += int(point["count"])
            current["cases"] = list(dict.fromkeys([*current["cases"], *point.get("cases", [])]))
    return [PainMapPoint(**point) for point in merged.values()]


@router.get("/address-cases/geocoding-stats", response_model=AddressCaseGeocodingStats)
async def address_case_geocoding_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AddressCaseGeocodingStats:
    """Сколько адресных кейсов уже имеют координаты в geo-кэше."""

    _require_superadmin(current_user)
    stats = await PainMapService(db).geocoding_stats()
    return AddressCaseGeocodingStats(**stats)


@router.post("/address-cases/geocode-revalidate")
async def address_case_geocode_revalidate(
    apply: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Перепроверяет найденные точки текущей отбраковкой, без запросов к геокодеру.

    Без `apply` только считает и показывает примеры — можно посмотреть, что
    именно снимется, прежде чем трогать кэш.
    """

    _require_superadmin(current_user)
    return await PainMapService(db).revalidate_geocode_cache(
        organization_id=current_user.organization_id,
        apply=apply,
    )


@router.post("/address-cases/geocode-revalidate-restore")
async def address_case_geocode_revalidate_restore(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Возвращает точки, снятые пересмотром. Запросов к геокодеру не делает."""

    _require_superadmin(current_user)
    return PainMapService(db).restore_revalidated_points()


@router.post("/address-cases/geocoding-backfill")
async def address_case_geocoding_backfill(
    max_new: int | None = Query(None, ge=1, le=200),
    retry_fresh_misses: bool = Query(False),
    only_revalidated: bool = Query(False),
    only_untried: bool = Query(False),
    only_unasked: bool = Query(False),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Запускает догеокодирование адресных кейсов фоновой задачей."""

    _require_superadmin(current_user)
    organization_id = current_user.organization_id
    job = await create_job(
        JobKind.address_geocoding_backfill,
        message="Подготовка догеокодинга адресных кейсов…",
    )

    async def runner(progress: ProgressReporter) -> dict:
        async with async_session_maker() as session:
            stats = await PainMapService(session).backfill_missing_geocodes(
                organization_id=organization_id,
                max_new=max_new,
                retry_fresh_misses=retry_fresh_misses,
                only_revalidated=only_revalidated,
                only_untried=only_untried,
                only_unasked=only_unasked,
                progress=progress,
            )
            return AddressCaseGeocodingBackfillResponse(**stats).model_dump()

    run_job_in_background(job, runner)
    return {"job_id": job.id}


@router.get("/address-cases/export")
async def export_address_cases(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(50_000, ge=1, le=200_000),
    only_with_case: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Выгружает сырые адресные кейсы из comment_analysis.hierarchy.case в XLSX.

    only_with_case=false снимает фильтр по адресу: тогда в выгрузку попадают
    и обращения без извлечённого места, и официальные ответы организаций. Без
    этого их нельзя посмотреть офлайн — прямого доступа к базе нет.
    """

    _require_superadmin(current_user)
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="date_from не может быть позже date_to",
        )

    event_at = func.coalesce(Comment.comment_date, Comment.created_at)
    case_expr = CommentAnalysis.hierarchy["case"].as_string()
    stmt = (
        select(
            Organization.id.label("organization_id"),
            Organization.name.label("organization_name"),
            Public.id.label("public_id"),
            Public.name.label("public_name"),
            Public.code.label("public_code"),
            Region.name.label("public_region"),
            Region.code.label("public_region_code"),
            PublicSocialLink.id.label("public_social_link_id"),
            PublicSocialLink.title.label("source_title"),
            PublicSocialLink.url.label("source_url"),
            PublicSocialLink.external_public_id.label("source_external_public_id"),
            SocialNetwork.code.label("social_network_code"),
            SocialNetwork.name.label("social_network_name"),
            Publication.id.label("publication_id"),
            Publication.url.label("publication_url"),
            Publication.external_post_id.label("external_post_id"),
            Publication.published_at.label("published_at"),
            Comment.id.label("comment_id"),
            Comment.external_id.label("external_comment_id"),
            Comment.parent_comment_id.label("parent_comment_id"),
            Comment.author_name.label("author_name"),
            Comment.author_external_id.label("author_external_id"),
            Comment.comment_date.label("comment_date"),
            Comment.parsed_at.label("parsed_at"),
            Comment.created_at.label("comment_created_at"),
            Comment.text.label("comment_text"),
            CommentAnalysis.id.label("analysis_id"),
            CommentAnalysis.relevance.label("relevance"),
            CommentAnalysis.sentiment.label("sentiment"),
            CommentAnalysis.author_type.label("author_type"),
            CommentAnalysis.message_type.label("message_type"),
            CommentAnalysis.is_official_response.label("is_official_response"),
            CommentAnalysis.classification_source.label("classification_source"),
            CommentAnalysis.classification_state.label("classification_state"),
            CommentAnalysis.needs_review.label("needs_review"),
            CommentAnalysis.model_version.label("model_version"),
            CommentAnalysis.analyzed_at.label("analyzed_at"),
            CommentAnalysis.summary.label("summary"),
            CommentAnalysis.topics.label("topics"),
            CommentAnalysis.hierarchy.label("hierarchy"),
            CommentAnalysis.entities.label("entities"),
            CommentAnalysis.candidates.label("candidates"),
        )
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .join(Organization, Organization.id == Public.organization_id)
        .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id, isouter=True)
        .join(Region, Region.id == Public.region_id, isouter=True)
        .where(Comment.is_deleted.is_(False))
        .order_by(event_at.desc())
        .limit(limit)
    )
    if only_with_case:
        stmt = stmt.where(func.coalesce(case_expr, "") != "")

    start = _dt_start(date_from)
    end = _dt_end_exclusive(date_to)
    if start is not None:
        stmt = stmt.where(event_at >= start)
    if end is not None:
        stmt = stmt.where(event_at < end)

    rows = (await db.execute(stmt)).mappings().all()

    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "address_cases"
    headers = [
        "organization_id",
        "organization_name",
        "public_id",
        "public_name",
        "public_code",
        "public_region",
        "public_region_code",
        "public_social_link_id",
        "source_title",
        "source_url",
        "source_external_public_id",
        "social_network_code",
        "social_network_name",
        "publication_id",
        "publication_url",
        "external_post_id",
        "published_at",
        "comment_id",
        "external_comment_id",
        "parent_comment_id",
        "author_name",
        "author_external_id",
        "comment_date",
        "parsed_at",
        "comment_created_at",
        "comment_text",
        "analysis_id",
        "relevance",
        "sentiment",
        "author_type",
        "message_type",
        "is_official_response",
        "classification_source",
        "classification_state",
        "needs_review",
        "model_version",
        "analyzed_at",
        "summary",
        "topics_json",
        "hierarchy_category",
        "hierarchy_subcategory",
        "hierarchy_case",
        "hierarchy_json",
        "entities_address",
        "entities_institution",
        "entities_reference_number",
        "entities_deadline",
        "entities_json",
        "candidates_json",
    ]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        hierarchy = row["hierarchy"] if isinstance(row["hierarchy"], dict) else {}
        entities = row["entities"] if isinstance(row["entities"], dict) else {}
        sheet.append([
            _excel_cell(row["organization_id"]),
            _excel_cell(row["organization_name"]),
            _excel_cell(row["public_id"]),
            _excel_cell(row["public_name"]),
            _excel_cell(row["public_code"]),
            _excel_cell(row["public_region"]),
            _excel_cell(row["public_region_code"]),
            _excel_cell(row["public_social_link_id"]),
            _excel_cell(row["source_title"]),
            _excel_cell(row["source_url"]),
            _excel_cell(row["source_external_public_id"]),
            _excel_cell(row["social_network_code"]),
            _excel_cell(row["social_network_name"]),
            _excel_cell(row["publication_id"]),
            _excel_cell(row["publication_url"]),
            _excel_cell(row["external_post_id"]),
            _iso(row["published_at"]),
            _excel_cell(row["comment_id"]),
            _excel_cell(row["external_comment_id"]),
            _excel_cell(row["parent_comment_id"]),
            _excel_cell(row["author_name"]),
            _excel_cell(row["author_external_id"]),
            _iso(row["comment_date"]),
            _iso(row["parsed_at"]),
            _iso(row["comment_created_at"]),
            _excel_cell(row["comment_text"]),
            _excel_cell(row["analysis_id"]),
            _excel_cell(row["relevance"]),
            _excel_cell(row["sentiment"]),
            _excel_cell(row["author_type"]),
            _excel_cell(row["message_type"]),
            bool(row["is_official_response"]),
            _excel_cell(row["classification_source"]),
            _excel_cell(row["classification_state"]),
            bool(row["needs_review"]),
            _excel_cell(row["model_version"]),
            _iso(row["analyzed_at"]),
            _excel_cell(row["summary"]),
            _json_cell(row["topics"]),
            _excel_cell(hierarchy.get("category")),
            _excel_cell(hierarchy.get("subcategory")),
            _excel_cell(hierarchy.get("case")),
            _json_cell(hierarchy),
            _excel_cell(entities.get("address")),
            _excel_cell(entities.get("institution")),
            _excel_cell(entities.get("reference_number")),
            _excel_cell(entities.get("deadline")),
            _json_cell(entities),
            _json_cell(row["candidates"]),
        ])

    sheet.freeze_panes = "A2"
    for column in ("A", "B", "D", "F", "I", "N", "O", "Z", "AP"):
        sheet.column_dimensions[column].width = 28
    buffer = io.BytesIO()
    workbook.save(buffer)

    period_bits = [
        date_from.isoformat() if date_from else "all",
        date_to.isoformat() if date_to else "all",
    ]
    filename = f"address-cases-{period_bits[0]}-{period_bits[1]}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/geo-cache/status", response_model=GeoCacheStatus)
async def geo_cache_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeoCacheStatus:
    """Диагностика файлового кэша геокодинга карты болей."""

    _require_geo_cache_admin(current_user)
    return GeoCacheStatus(**PainMapService(db).cache_status())


@router.get("/quality-report")
async def quality_report(
    since: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Метрики качества разметки: подкатегории и адреса.

    Считается на сервере — тут есть и база, и geo-cache. Нужна, чтобы снимать
    «до/после» с машины разработчика, у которой прямого доступа к БД нет.
    """

    _require_geo_cache_admin(current_user)
    parsed_since = datetime.fromisoformat(since) if since else None
    return await build_quality_report(db, parsed_since)


@router.get("/geo-keys")
async def geo_keys_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Расход ключей геокодера за сутки. Сами ключи не отдаём, только хвосты."""

    _require_geo_cache_admin(current_user)
    set_runtime_keys(await get_yandex_geocoder_keys(db))
    return key_usage()


@router.put("/geo-keys")
async def geo_keys_update(
    payload: GeoKeysRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Меняет список ключей без передеплоя: на сервере правка .env затруднена."""

    _require_superadmin(current_user)
    saved = await set_yandex_geocoder_keys(db, payload.keys)
    await db.commit()
    set_runtime_keys(saved)
    return key_usage()


@router.post("/geo-cache/rotate", response_model=GeoCacheRotateResponse)
async def geo_cache_rotate(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GeoCacheRotateResponse:
    """Переименовывает текущий geo-cache в backup и освобождает путь для нового файла."""

    _require_geo_cache_admin(current_user)
    try:
        return GeoCacheRotateResponse(**PainMapService(db).rotate_cache())
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Не удалось ротировать geo-cache: {exc}",
        ) from exc


@router.get("/incidents", response_model=list[Incident])
async def incidents(
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Incident]:
    """Реестр инцидентов (лайт): адресные кейсы + организация + статус (из reaction-gap)."""

    link = None
    if public_social_link_id:
        try:
            link = uuid.UUID(public_social_link_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    rows = await IncidentsService(db).incidents(
        current_user,
        link_id=link,
        municipality_name=_municipality_filter(municipality_name),
    )
    return [Incident(**i) for i in rows]


@router.get("/agency-ranking", response_model=list[AgencyStat])
async def agency_ranking(
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AgencyStat]:
    """Рейтинг организаций по реакции на обращения (по инцидентам)."""

    link = None
    if public_social_link_id:
        try:
            link = uuid.UUID(public_social_link_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    rows = await AgencyRankingService(db).rank(
        current_user,
        link_id=link,
        municipality_name=_municipality_filter(municipality_name),
    )
    return [AgencyStat(**r) for r in rows]


@router.get("/alerts", response_model=list[Alert])
async def alerts(
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Alert]:
    """Всплески обращений по категориям (последнее окно против предыдущего)."""

    try:
        links = parse_public_social_link_ids(public_social_link_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    rows = await AlertsService(db).alerts(
        current_user,
        link_id=(links[0] if len(links) == 1 else links or None),
        municipality_name=_municipality_filter(municipality_name),
    )
    return [Alert(**a) for a in rows]


@router.post("/case-comments", response_model=list[CaseComment])
async def case_comments(
    payload: CaseCommentsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CaseComment]:
    """Комментарии адресных кейсов точки карты (drill-down по клику)."""

    try:
        links = parse_public_social_link_ids(payload.public_social_link_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_social_link_id") from exc
    rows = await PainMapService(db).case_comments(
        current_user,
        payload.cases,
        since=period_to_since(payload.period),
        link_id=(links[0] if len(links) == 1 else links or None),
        problem_type=(payload.problem_type or "").strip() or None,
        municipality_name=_municipality_filter(payload.municipality_name),
    )
    return [CaseComment(**r) for r in rows]


@router.post("/address-cases/delete", response_model=AddressCaseDeleteResponse)
async def delete_address_case(
    payload: AddressCaseDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AddressCaseDeleteResponse:
    """Помечает выбранные кейсы карты как неадресные в текущей организации."""

    _require_superadmin(current_user)
    result = await PainMapService(db).mark_cases_non_address(current_user, payload.cases)
    return AddressCaseDeleteResponse(**result)


@router.delete("/publics/{public_id}", response_model=DeleteImportedPublicResponse)
async def delete_imported_public(
    public_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeleteImportedPublicResponse:
    """Удаляет импортированную площадку и пересобирает VK-аналитику."""
    try:
        result = await ImportedPublicDeleteService(db).delete_public(current_user, public_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DeleteImportedPublicResponse(public_id=public_id, **result)


@router.get("/regions", response_model=list[RegionOption])
async def list_regions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[RegionOption]:
    """Справочник регионов для привязки площадок."""

    rows = (
        await db.execute(
            select(Region).order_by(Region.name.asc())
        )
    ).scalars().all()
    return [
        RegionOption(id=str(region.id), name=region.name, code=region.code)
        for region in rows
    ]


@router.post("/publics/infer-location", response_model=PublicLocationInferenceResponse)
async def infer_public_locations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublicLocationInferenceResponse:
    """Автоматически заполняет регион/муниципалитет у площадок без привязки."""

    _require_superadmin(current_user)
    result = await PublicLocationInferenceService(db).infer_missing()
    return PublicLocationInferenceResponse(**result)


@router.patch("/publics/{public_id}/region", response_model=PublicRegionResponse)
async def update_public_region(
    public_id: str,
    payload: PublicRegionUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PublicRegionResponse:
    """Задаёт регион, на который распространяется паблик."""

    _require_public_settings_admin(current_user)
    try:
        public_uuid = uuid.UUID(public_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный public_id") from exc

    public = (
        await db.execute(
            select(Public)
            .where(Public.id == public_uuid)
            .where(Public.organization_id == current_user.organization_id)
        )
    ).scalar_one_or_none()
    if public is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Паблик не найден")

    region = None
    if payload.region_id:
        try:
            region_uuid = uuid.UUID(payload.region_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Невалидный region_id") from exc
        region = (
            await db.execute(select(Region).where(Region.id == region_uuid))
        ).scalar_one_or_none()
        if region is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Регион не найден")
        public.region_id = region.id
    else:
        public.region_id = None

    municipality_name = (payload.municipality_name or "").strip()
    if municipality_name:
        if not is_krasnoyarsk_region_name(region.name if region else None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Муниципалитет можно выбрать только для Красноярского края",
            )
        canonical = canonical_municipality_name(municipality_name)
        if canonical is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Неизвестный муниципалитет Красноярского края",
            )
        public.municipality_name = canonical
    else:
        public.municipality_name = None

    await db.commit()
    return PublicRegionResponse(
        public_id=str(public.id),
        region_id=str(region.id) if region else None,
        region_name=region.name if region else None,
        municipality_name=public.municipality_name,
    )


@router.get("/diagnostics/slow")
async def slow_request_diagnostics(
    current_user: User = Depends(get_current_user),
) -> dict:
    """Последние медленные ответы и текущая задержка цикла событий.

    Логи сервера недоступны, а лента Sentry Logs включается на стороне трекера.
    Эта ручка отдаёт те же замеры прямо в браузер.
    """

    return slow_requests_snapshot()


@router.get("/publics")
async def list_publics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Импортированные площадки с метриками — только те, что доступны актору.

    Миньон видит лишь сообщества, на которые ему выдан view_community. Отдавать
    полный список «для галочки» нельзя: названия сообществ — тоже данные.
    Админ/суперадмин получают всё (accessible_community_ids вернёт None).
    """
    publics = await PublicQueryService(PublicQueryRepository(db)).list_publics(current_user)

    allowed = await accessible_community_ids(db, current_user, PermissionEnum.view_community)
    if allowed is None:
        return publics

    allowed_str = {str(pid) for pid in allowed}
    return [item for item in publics if item["id"] in allowed_str]


@router.get("/publications")
async def list_publications(
    public_social_link_id: str | None = None,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Возвращает публикации организации."""

    return await PublicQueryService(PublicQueryRepository(db)).list_publications(
        current_user,
        public_social_link_id=public_social_link_id,
        limit=limit,
    )


@router.get("/comments")
async def list_recent_comments(
    publication_id: str | None = None,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Возвращает последние комментарии организации."""
    return await PublicQueryService(PublicQueryRepository(db)).list_recent_comments(
        current_user,
        publication_id=publication_id,
        limit=limit,
    )


@router.post("/pains/{pain_id}/regenerate-strategy", response_model=StrategyRegenerateResponse)
async def regenerate_pain_strategy(
    pain_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StrategyRegenerateResponse:
    """Генерирует новую LLM-стратегию по боли."""

    try:
        return await PainStrategyRegenerationService(db).regenerate(current_user, pain_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("LLM regenerate strategy failed | pain_id=%s | error=%s", pain_id, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM-сервис недоступен, попробуйте позже") from exc


@router.get("/publications/pains-breakdown", response_model=list[PublicationPainBucket])
async def publication_pains_breakdown(
    url: str | None = None,
    publication_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PublicationPainBucket]:
    """Возвращает breakdown комментариев публикации по болям."""

    try:
        return await PublicationPainBreakdownService(db).get_breakdown(
            current_user,
            url=url,
            publication_id=publication_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/pains/trends", response_model=list[PainTrendItem])
async def list_pain_trends(
    period: str = "all",
    public_social_link_id: str | None = None,
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PainTrendItem]:
    """Возвращает weekly trends по болям за выбранный период (как карточка)."""

    try:
        link_ids = parse_public_social_link_ids(public_social_link_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Невалидный public_social_link_id",
        ) from exc
    return await PainTrendsService(db).list_trends(
        current_user,
        since=period_to_since(period),
        link_id=(link_ids[0] if len(link_ids) == 1 else link_ids or None),
        municipality_name=_municipality_filter(municipality_name),
    )


@router.get("/pains/{pain_id}/events", response_model=list[PainEventLink])
async def list_pain_events(
    pain_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PainEventLink]:
    """Возвращает события и посты, связанные с болью."""

    try:
        return await PainEventsService(db).list_events(current_user, pain_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/pains/{pain_id}", response_model=PainDetailResponse)
async def get_pain_detail(
    pain_id: str,
    public_social_link_id: str | None = None,
    period: str = "all",
    municipality_name: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PainDetailResponse:
    """Возвращает детальную карточку боли."""

    try:
        return await PainDetailService(db).get_detail(
            current_user,
            pain_id,
            public_social_link_id=public_social_link_id,
            period=period,
            municipality_name=_municipality_filter(municipality_name),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/pains/{pain_id}/comments", response_model=PainCommentsPage)
async def list_pain_comments(
    pain_id: str,
    subcategory: str | None = None,
    public_social_link_id: str | None = None,
    period: str = "all",
    municipality_name: str | None = None,
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PainCommentsPage:
    """Возвращает пагинируемые комментарии боли."""
    try:
        return await PainCommentsService(db).list_comments(
            current_user,
            pain_id,
            subcategory=subcategory,
            public_social_link_id=public_social_link_id,
            period=period,
            municipality_name=_municipality_filter(municipality_name),
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
