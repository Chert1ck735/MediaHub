"""Очередь классификации комментариев и фоновый async worker.

Комментарий при ingest попадает в очередь (CommentAnalysis.classification_state='pending'),
воркер берёт pending пачками, гоняет через LLM и переводит в done/failed.
Rebuild аналитики LLM сам не вызывает — работает с готовыми comment_analysis.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Callable, Iterable
from uuid import UUID

from sqlalchemy import and_, case as sa_case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.analytics import llm_health
from backend.modules.analytics.llm_coordination import (
    worker_should_idle,
    is_formation_active,
)
from backend.db.comment_analysis import CommentAnalysis
from backend.db.comments import Comment
from backend.db.public_social_links import PublicSocialLink
from backend.db.publics import Public
from backend.db.publications import Publication
from backend.modules.analytics.services.comment_analysis_service import apply_llm_analysis
from backend.modules.analytics.services.pain_map_service import PainMapService
from backend.modules.llm import service as llm_service
from backend.modules.llm.interfaces import LLMError

logger = logging.getLogger(__name__)
AnalysisPayloadApplier = Callable[..., None]


# Возможные значения classification_state.
STATE_PENDING = "pending"
STATE_PROCESSING = "processing"
STATE_DONE = "done"
STATE_FAILED = "failed"
STATE_SKIPPED = "skipped"  # снят с очереди вручную; воркер не берёт
SOURCE_NEEDS_REVIEW = "needs_review"
SOURCE_LLM_NEEDS_REVIEW = "llm_needs_review"
SOURCE_LLM_MANUAL = "llm_manual"

MAX_LLM_RETRIES = 2            # ретраи внутри одной батч-попытки (сеть мигнула)

# Батч-попытки: после неудачи запись возвращается в очередь с экспоненциальной
# паузой; исчерпала лимит — failed окончательно (next_attempt_at = NULL).
MAX_CLASSIFY_ATTEMPTS = 5
RETRY_BACKOFF_BASE_S = 300     # 5 минут после первой неудачи
RETRY_BACKOFF_FACTOR = 3.0     # 5м → 15м → 45м → 2ч15м
RETRY_BACKOFF_CAP_S = 6 * 3600

# Queue performance is calculated on the server from persisted successful LLM
# completion timestamps.  Five minutes reacts quickly enough to a changing
# worker rate, while the contiguous historical tail gives a useful estimate
# immediately after opening the UI or after a new queue has been created.
RATE_RECENT_WINDOW_SECONDS = 5 * 60
RATE_MAX_ACTIVE_GAP_SECONDS = 60 * 60
RATE_MIN_OBSERVATION_SECONDS = 30
RATE_HISTORY_LIMIT = 2000
RATE_HISTORY_BATCH_LIMIT = 12
RATE_DEFAULT_PER_MINUTE = 1.0
LLM_COMPLETION_SOURCES = ("llm", "llm_other", SOURCE_LLM_NEEDS_REVIEW)


def retry_delay_s(attempts: int) -> float:
    """Пауза до следующей попытки после ``attempts`` неудач."""

    power = max(attempts - 1, 0)
    return min(RETRY_BACKOFF_BASE_S * RETRY_BACKOFF_FACTOR**power, RETRY_BACKOFF_CAP_S)


def register_failed_attempt(analysis: CommentAnalysis, *, now: datetime) -> None:
    """Инкрементирует счётчик неудач и планирует ретрай либо хоронит запись."""

    attempts = int(analysis.classification_attempts or 0) + 1
    analysis.classification_attempts = attempts
    analysis.classification_state = STATE_FAILED
    if attempts < MAX_CLASSIFY_ATTEMPTS:
        analysis.next_attempt_at = now + timedelta(seconds=retry_delay_s(attempts))
    else:
        analysis.next_attempt_at = None


@dataclass
class ClassificationStats:
    """Статистика обработки одного batch воркера классификации."""

    picked: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    durations_ms: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Сериализует статистику; avg_ms — среднее время на коммент (None, если пусто)."""

        avg = (
            sum(self.durations_ms) / len(self.durations_ms)
            if self.durations_ms
            else None
        )
        return {
            "picked": self.picked,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "avg_ms": round(avg, 1) if avg is not None else None,
        }


@dataclass(frozen=True)
class QueuePerformance:
    """Пропускная способность очереди классификации и оценка времени до конца."""

    rate_per_minute: float
    eta_minutes: int
    rate_source: str
    rate_window_seconds: int
    rate_sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate_per_minute": round(self.rate_per_minute, 1),
            "eta_minutes": self.eta_minutes,
            "rate_source": self.rate_source,
            "rate_window_seconds": self.rate_window_seconds,
            "rate_sample_size": self.rate_sample_size,
        }


# ---------------------------------------------------------------------------
# Постановка задач в очередь
# ---------------------------------------------------------------------------


async def mark_comment_pending(db: AsyncSession, comment_id: UUID) -> None:
    """Ставит комментарий в очередь: создаёт CommentAnalysis при отсутствии, done/processing не трогает."""

    existing = await db.execute(
        select(CommentAnalysis).where(CommentAnalysis.comment_id == comment_id)
    )
    analysis = existing.scalar_one_or_none()
    if analysis is None:
        analysis = CommentAnalysis(
            comment_id=comment_id,
            classification_state=STATE_PENDING,
        )
        db.add(analysis)
        return
    # Не сбрасываем уже успешно классифицированные записи.
    if analysis.classification_state in {STATE_DONE, STATE_PROCESSING}:
        return
    analysis.classification_state = STATE_PENDING


async def mark_organization_for_reclassify(
    db: AsyncSession,
    organization_id: UUID,
    *,
    scope: str = "review",
) -> int:
    """Массово возвращает CommentAnalysis организации в pending.

    scope: all (все) | failed (только ошибки) | review (rule-needs-review/unknown/NULL)
    | unclassified (pending/skipped/failed/rule-review + записи без CommentAnalysis).
    Скоуп по организации даёт tenant isolation. Возвращает число записей.
    """

    if scope == "unclassified":
        existing_q = (
            select(CommentAnalysis.id)
            .select_from(CommentAnalysis)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == organization_id)
            .where(Comment.is_deleted.is_(False))
            .where(CommentAnalysis.classification_state != STATE_PROCESSING)
            .where(
                (CommentAnalysis.classification_state.in_([STATE_PENDING, STATE_FAILED, STATE_SKIPPED]))
                | (CommentAnalysis.classification_source == "unknown")
                | (CommentAnalysis.classification_source.is_(None))
                | (CommentAnalysis.analyzed_at.is_(None))
                | (
                    (CommentAnalysis.classification_source == SOURCE_NEEDS_REVIEW)
                    & (CommentAnalysis.model_version.like("vk_rule_based%"))
                )
            )
        )
        existing_ids = [row[0] for row in (await db.execute(existing_q)).all()]
        if existing_ids:
            await db.execute(
                update(CommentAnalysis)
                .where(CommentAnalysis.id.in_(existing_ids))
                .values(classification_state=STATE_PENDING, classification_attempts=0, next_attempt_at=None)
            )

        missing_q = (
            select(Comment.id)
            .select_from(Comment)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .outerjoin(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .where(Public.organization_id == organization_id)
            .where(Comment.is_deleted.is_(False))
            .where(CommentAnalysis.id.is_(None))
        )
        missing_ids = [row[0] for row in (await db.execute(missing_q)).all()]
        for comment_id in missing_ids:
            db.add(
                CommentAnalysis(
                    comment_id=comment_id,
                    classification_state=STATE_PENDING,
                )
            )
        return len(existing_ids) + len(missing_ids)

    base_q = (
        select(CommentAnalysis.id)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Public.organization_id == organization_id)
    )

    if scope == "failed":
        base_q = base_q.where(CommentAnalysis.classification_state == STATE_FAILED)
    elif scope == "review":
        base_q = base_q.where(
            (CommentAnalysis.classification_source == "unknown")
            | (CommentAnalysis.classification_source.is_(None))
            | (
                (CommentAnalysis.classification_source == SOURCE_NEEDS_REVIEW)
                & (CommentAnalysis.model_version.like("vk_rule_based%"))
            )
        )
    elif scope != "all":
        raise ValueError(f"Unknown reclassify scope: {scope}")

    rows = await db.execute(base_q)
    ids = [row[0] for row in rows.all()]
    if not ids:
        return 0

    await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.id.in_(ids))
        .values(classification_state=STATE_PENDING, classification_attempts=0, next_attempt_at=None)
    )
    return len(ids)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


async def reset_stale_processing(db: AsyncSession, *, older_than_seconds: int = 1800) -> int:
    """Возвращает зависшие в processing записи (после краша воркера) обратно в pending."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    result = await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.classification_state == STATE_PROCESSING)
        .where(CommentAnalysis.updated_at < cutoff)
        .values(classification_state=STATE_PENDING, classification_attempts=0, next_attempt_at=None)
    )
    await db.commit()
    requeued = result.rowcount or 0
    if requeued:
        logger.info("Requeued %d stale 'processing' analyses", requeued)
    return requeued


async def reap_ghost_analyses(
    db: AsyncSession, *, organization_id: Optional[UUID] = None
) -> int:
    """Снимает с очереди записи, которые никогда не станут ``done``.

    «Призраки» — это pending/processing, которые LLM не осмыслит в принципе:
    пустой текст и комментарии от самого сообщества (``from_id`` < 0). Снапшот
    их и так отбрасывает детерминированно, но в очереди они висели вечно и
    расходились со счётчиком: очередь считает pending+processing, а воркер
    берёт только pending.

    Терминалом берём существующий ``skipped`` — воркер такие не claim'ит,
    а счётчики очереди их не показывают.
    """

    ghost = or_(
        func.btrim(func.coalesce(Comment.text, "")) == "",
        func.btrim(func.coalesce(Comment.author_external_id, "")).like("-%"),
    )
    ids_q = (
        select(CommentAnalysis.id)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .where(CommentAnalysis.classification_state.in_([STATE_PENDING, STATE_PROCESSING]))
        .where(Comment.is_deleted.is_(False))
        .where(ghost)
    )
    if organization_id is not None:
        ids_q = (
            ids_q.join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == organization_id)
        )

    ids = [row[0] for row in (await db.execute(ids_q)).all()]
    if not ids:
        return 0

    await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.id.in_(ids))
        .values(classification_state=STATE_SKIPPED)
    )
    await db.commit()
    logger.info("Reaped %d ghost analyses from classification queue", len(ids))
    return len(ids)


async def auto_rebuild_snapshots(db_factory) -> int:
    """Пересобирает боли (агрегация без LLM) по готовой классификации.

    Вызывается воркером, когда очередь разгребена, чтобы боли обновлялись сами,
    без ручной кнопки «Сформировать». force_reclassify=False — LLM не гоняется.
    """
    from backend.db.users import User
    from backend.modules.analytics.services.analytics_refresh_service import AnalyticsRefreshService

    async with db_factory() as session:
        org_ids = (await session.execute(
            select(Public.organization_id).where(Public.organization_id.isnot(None)).distinct()
        )).scalars().all()

    rebuilt = 0
    for org_id in org_ids:
        try:
            async with db_factory() as session:
                user = (await session.execute(
                    select(User).where(User.organization_id == org_id).limit(1)
                )).scalar_one_or_none()
                if user is None:
                    continue
                await AnalyticsRefreshService(session).refresh(user, force_reclassify=False)
                rebuilt += 1
        except Exception:
            logger.exception("Auto-rebuild snapshot failed for org %s", org_id)
    if rebuilt:
        logger.info("Auto-rebuilt %d org snapshot(s) after classification drain", rebuilt)
    return rebuilt


async def requeue_low_confidence(
    db: AsyncSession, *, limit: int = 200, organization_id: Optional[UUID] = None,
) -> int:
    """Возвращает в очередь на LLM ненадёжно классифицированные комменты.

    rule-based/needs_review категории ненадёжны — переклассифицируем их LLM
    фоном. После LLM источник становится ``llm`` / ``llm_needs_review`` →
    повторно не берутся (монотонно).
    """
    sub = (
        select(CommentAnalysis.id)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .where(
            or_(
                CommentAnalysis.classification_source == "rule_based",
                and_(
                    CommentAnalysis.classification_source == SOURCE_NEEDS_REVIEW,
                    CommentAnalysis.model_version.like("vk_rule_based%"),
                ),
            )
        )
        .where(CommentAnalysis.classification_state.notin_([STATE_PROCESSING, STATE_PENDING, STATE_SKIPPED]))
        .where(Comment.is_deleted.is_(False))
        .limit(limit)
    )
    if organization_id is not None:
        sub = (
            sub.join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == organization_id)
        )
    ids = [row[0] for row in (await db.execute(sub)).all()]
    if not ids:
        return 0
    await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.id.in_(ids))
        .values(classification_state=STATE_PENDING, classification_attempts=0, next_attempt_at=None)
    )
    await db.commit()
    return len(ids)


def _manual_review_source_filter():
    """Терминальный LLM-review плюс старые LLM needs_review до ввода нового source."""

    return or_(
        CommentAnalysis.classification_source == SOURCE_LLM_NEEDS_REVIEW,
        and_(
            CommentAnalysis.classification_source == SOURCE_NEEDS_REVIEW,
            or_(
                CommentAnalysis.model_version.is_(None),
                CommentAnalysis.model_version.notlike("vk_rule_based%"),
            ),
        ),
    )


async def count_manual_review(
    db: AsyncSession, *, organization_id: UUID | None = None
) -> int:
    """Сколько LLM-классификаций требуют ручного назначения категории."""

    q = (
        select(func.count(CommentAnalysis.id))
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Comment.is_deleted.is_(False))
        .where(CommentAnalysis.classification_state == STATE_DONE)
        .where(_manual_review_source_filter())
    )
    if organization_id is not None:
        q = q.where(Public.organization_id == organization_id)
    return int((await db.execute(q)).scalar() or 0)


async def list_manual_review(
    db: AsyncSession,
    *,
    organization_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """Комментарии, где LLM закончила работу, но категорию нужно выбрать вручную."""

    base = (
        select(
            CommentAnalysis.id.label("analysis_id"),
            Comment.id.label("comment_id"),
            Comment.text,
            Comment.comment_date,
            CommentAnalysis.summary,
            CommentAnalysis.sentiment,
            CommentAnalysis.message_type,
            CommentAnalysis.hierarchy,
            Publication.url.label("publication_url"),
            Public.name.label("public_name"),
        )
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Public.organization_id == organization_id)
        .where(Comment.is_deleted.is_(False))
        .where(CommentAnalysis.classification_state == STATE_DONE)
        .where(_manual_review_source_filter())
    )
    total = int((await db.execute(select(func.count()).select_from(base.subquery()))).scalar() or 0)
    rows = (
        await db.execute(
            base.order_by(CommentAnalysis.updated_at.asc(), CommentAnalysis.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
    ).mappings().all()
    return total, [
        {
            "analysis_id": str(row["analysis_id"]),
            "comment_id": str(row["comment_id"]),
            "text": row["text"] or "",
            "summary": row["summary"],
            "sentiment": getattr(row["sentiment"], "value", row["sentiment"]),
            "message_type": row["message_type"],
            "hierarchy": row["hierarchy"] or {},
            "public_name": row["public_name"],
            "publication_url": row["publication_url"],
            "comment_date": row["comment_date"].isoformat() if row["comment_date"] else None,
        }
        for row in rows
    ]


async def resolve_manual_review(
    db: AsyncSession,
    analysis_id: UUID,
    *,
    organization_id: UUID,
    category: str,
    subcategory: str = "",
    case_name: str = "",
) -> bool:
    """Сохраняет ручную категорию и выводит комментарий из manual review."""

    analysis = (
        await db.execute(
            select(CommentAnalysis)
            .join(Comment, Comment.id == CommentAnalysis.comment_id)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(CommentAnalysis.id == analysis_id)
            .where(Public.organization_id == organization_id)
            .where(Comment.is_deleted.is_(False))
            .where(_manual_review_source_filter())
        )
    ).scalar_one_or_none()
    if analysis is None:
        return False

    analysis.hierarchy = {
        "category": category.strip(),
        "subcategory": subcategory.strip(),
        "case": case_name.strip(),
    }
    analysis.classification_source = SOURCE_LLM_MANUAL
    analysis.classification_state = STATE_DONE
    analysis.needs_review = False
    await db.commit()
    return True


def _utc(value: datetime) -> datetime:
    """Приводит значение к UTC с часовым поясом: SQLite в тестах отдаёт наивные даты."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _completion_groups(
    timestamps: Iterable[datetime],
    *,
    now: datetime,
) -> list[tuple[datetime, int]]:
    """Сводит одинаковые ``analyzed_at`` одной пачки в одно событие завершения."""

    now_utc = _utc(now)
    # Ignore timestamps too far in the future: one host with a bad clock must
    # not turn the rate into a negative/near-infinite value.
    latest_valid = now_utc + timedelta(minutes=1)
    counts = Counter(
        ts
        for value in timestamps
        if value is not None and (ts := _utc(value)) <= latest_valid
    )
    return sorted(counts.items(), key=lambda item: item[0])


def _contiguous_tail(
    groups: list[tuple[datetime, int]],
) -> list[tuple[datetime, int]]:
    """Оставляет последний непрерывный прогон, отбрасывая долгие простои между ними."""

    if not groups:
        return []
    tail = [groups[-1]]
    for item in reversed(groups[:-1]):
        if len(tail) >= RATE_HISTORY_BATCH_LIMIT:
            break
        gap_seconds = (tail[0][0] - item[0]).total_seconds()
        if gap_seconds > RATE_MAX_ACTIVE_GAP_SECONDS:
            break
        tail.insert(0, item)
    return tail


def estimate_completion_rate(
    timestamps: Iterable[datetime],
    *,
    now: datetime | None = None,
) -> tuple[float, str, int, int]:
    """Оценивает скорость классификации в записях в минуту по отметкам времени.

    Воркер намеренно ставит всей пачке один ``analyzed_at``. При двух и более
    пачках первая берётся за точку отсчёта, а на прошедшее время делятся только
    последующие — иначе пачка, записанная одним мгновением, дала бы бесконечную
    скорость. Долгие простои разделяют независимые прогоны.
    """

    now_utc = _utc(now or datetime.now(timezone.utc))
    groups = _completion_groups(timestamps, now=now_utc)
    recent_cutoff = now_utc - timedelta(seconds=RATE_RECENT_WINDOW_SECONDS)
    recent = [item for item in groups if item[0] >= recent_cutoff]

    if len(recent) >= 2:
        active = _contiguous_tail(recent)
        first_at = active[0][0]
        last_at = active[-1][0]
        completed = sum(count for _, count in active[1:])
        elapsed = max(
            RATE_MIN_OBSERVATION_SECONDS,
            (last_at - first_at).total_seconds(),
        )
        rate = completed * 60.0 / elapsed
        return max(rate, 0.1), "recent", round(elapsed), sum(c for _, c in active)

    active_history = _contiguous_tail(groups)
    if len(active_history) >= 2:
        first_at = active_history[0][0]
        last_at = active_history[-1][0]
        completed = sum(count for _, count in active_history[1:])
        elapsed = max(
            RATE_MIN_OBSERVATION_SECONDS,
            (last_at - first_at).total_seconds(),
        )
        rate = completed * 60.0 / elapsed
        return max(rate, 0.1), "historical", round(elapsed), sum(c for _, c in active_history)

    if recent:
        completed = recent[-1][1]
        # One completion timestamp says nothing about how long that batch ran.
        # Do not turn a batch of 50 into an invented 50/min throughput.
        return RATE_DEFAULT_PER_MINUTE, "single_batch_default", 0, completed

    if groups:
        completed = groups[-1][1]
        return RATE_DEFAULT_PER_MINUTE, "single_batch_default", 0, completed

    return RATE_DEFAULT_PER_MINUTE, "default", 0, 0


def _classification_completion_timestamps_query(
    organization_id: UUID,
):
    """Запрос завершений LLM по организации — без записей, размеченных вручную."""

    return (
        select(CommentAnalysis.analyzed_at)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Public.organization_id == organization_id)
        .where(Comment.is_deleted.is_(False))
        # A row put back into pending still has its previous analyzed_at.  Only
        # its latest successful terminal state is a completion for this run.
        .where(CommentAnalysis.classification_state == STATE_DONE)
        .where(CommentAnalysis.analyzed_at.is_not(None))
        .where(CommentAnalysis.classification_source != SOURCE_LLM_MANUAL)
        .where(
            or_(
                CommentAnalysis.classification_source.in_(LLM_COMPLETION_SOURCES),
                and_(
                    CommentAnalysis.classification_source == "fallback",
                    CommentAnalysis.model_version.is_not(None),
                    func.lower(CommentAnalysis.model_version).not_like("%rule_based%"),
                ),
            )
        )
        .order_by(CommentAnalysis.analyzed_at.desc())
        .limit(RATE_HISTORY_LIMIT)
    )


def _latest_retry_at_query(organization_id: UUID):
    """Ближайшая запланированная повторная попытка, задерживающая разбор очереди."""

    return (
        select(func.max(CommentAnalysis.next_attempt_at))
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Public.organization_id == organization_id)
        .where(Comment.is_deleted.is_(False))
        .where(CommentAnalysis.classification_state == STATE_FAILED)
        .where(CommentAnalysis.next_attempt_at.is_not(None))
    )


async def estimate_queue_performance(
    db: AsyncSession,
    *,
    organization_id: UUID,
    remaining: int,
    failed_retrying: int = 0,
    now: datetime | None = None,
) -> QueuePerformance:
    """Скорость обработки и оценка времени до конца очереди одной организации."""

    observed_at = now or datetime.now(timezone.utc)
    rows = await db.execute(_classification_completion_timestamps_query(organization_id))
    timestamps = [row[0] for row in rows.all() if row[0] is not None]
    rate, source, window_seconds, sample_size = estimate_completion_rate(
        timestamps,
        now=observed_at,
    )
    remaining_count = max(0, int(remaining or 0))
    retrying_count = max(0, int(failed_retrying or 0))
    eta_minutes = 0
    if remaining_count:
        base_minutes = remaining_count / rate
        retry_tail_minutes = retrying_count / rate
        if retrying_count:
            latest_retry_at = (
                await db.execute(_latest_retry_at_query(organization_id))
            ).scalar_one_or_none()
            if latest_retry_at is not None:
                now_utc = _utc(observed_at)
                retry_wait_minutes = max(
                    0.0,
                    (_utc(latest_retry_at) - now_utc).total_seconds() / 60.0,
                )
                retry_tail_minutes += retry_wait_minutes
        eta_minutes = max(1, math.ceil(max(base_minutes, retry_tail_minutes)))
    return QueuePerformance(
        rate_per_minute=rate,
        eta_minutes=eta_minutes,
        rate_source=source,
        rate_window_seconds=window_seconds,
        rate_sample_size=sample_size,
    )


async def count_classification_states(
    db: AsyncSession, *, organization_id: UUID | None = None
) -> dict[str, int]:
    """Сколько CommentAnalysis в каждом статусе — для индикатора очереди в UI.

    ``failed`` дополнительно разбивается: ``failed_retrying`` — ждут повтора
    (next_attempt_at выставлен), остальные упали окончательно.
    """
    q = (
        select(
            CommentAnalysis.classification_state,
            func.count(),
            func.count().filter(CommentAnalysis.next_attempt_at.is_not(None)),
        )
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .where(Comment.is_deleted.is_(False))
        .group_by(CommentAnalysis.classification_state)
    )
    if organization_id is not None:
        q = (
            q.join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == organization_id)
        )
    out = {STATE_PENDING: 0, STATE_PROCESSING: 0, STATE_DONE: 0, STATE_FAILED: 0,
           "failed_retrying": 0}
    for state, cnt, retrying in (await db.execute(q)).all():
        out[str(state)] = int(cnt or 0)
        if str(state) == STATE_FAILED:
            out["failed_retrying"] = int(retrying or 0)
    return out


async def count_queue_by_public(
    db: AsyncSession, *, organization_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Очередь классификации в разбивке по пабликам — расшифровка индикатора в UI."""
    q = (
        select(
            Public.id,
            Public.name,
            CommentAnalysis.classification_state,
            func.count(),
        )
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Comment.is_deleted.is_(False))
        .where(
            CommentAnalysis.classification_state.in_([STATE_PENDING, STATE_PROCESSING])
        )
        .group_by(Public.id, Public.name, CommentAnalysis.classification_state)
    )
    if organization_id is not None:
        q = q.where(Public.organization_id == organization_id)

    acc: dict[UUID, dict[str, Any]] = {}
    for public_id, name, state, cnt in (await db.execute(q)).all():
        row = acc.setdefault(
            public_id,
            {"public_id": str(public_id), "name": name, "pending": 0, "processing": 0},
        )
        if state == STATE_PROCESSING:
            row["processing"] = int(cnt or 0)
        else:
            row["pending"] = int(cnt or 0)

    return sorted(
        acc.values(),
        key=lambda r: r["pending"] + r["processing"],
        reverse=True,
    )


async def skip_public_queue(
    db: AsyncSession,
    public_id: UUID,
    *,
    organization_id: UUID,
) -> int:
    """Снимает pending-комменты паблика с очереди (state→skipped). Скоуп по орге — защита.

    Реверсивно: полная переклассификация (scope='all') вернёт их в pending.
    """
    rows = await db.execute(
        select(CommentAnalysis.id)
        .select_from(CommentAnalysis)
        .join(Comment, Comment.id == CommentAnalysis.comment_id)
        .join(Publication, Publication.id == Comment.publication_id)
        .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
        .join(Public, Public.id == PublicSocialLink.public_id)
        .where(Public.id == public_id)
        .where(Public.organization_id == organization_id)
        .where(CommentAnalysis.classification_state == STATE_PENDING)
    )
    ids = [row[0] for row in rows.all()]
    if not ids:
        return 0
    await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.id.in_(ids))
        .values(classification_state=STATE_SKIPPED)
    )
    await db.commit()
    return len(ids)


async def _claim_batch(
    db: AsyncSession,
    *,
    limit: int,
    organization_id: Optional[UUID] = None,
) -> list[tuple[UUID, UUID, str]]:
    """Берёт до limit pending-записей (старые первыми, FOR UPDATE SKIP LOCKED),
    переводит их в processing и возвращает список (analysis_id, comment_id, text)."""

    q = (
        select(
            CommentAnalysis.id,
            Comment.id.label("comment_id"),
            Comment.text,
        )
        .select_from(CommentAnalysis)
        .join(
            Comment,
            Comment.id == CommentAnalysis.comment_id,
        )
        .where(
            or_(
                CommentAnalysis.classification_state == STATE_PENDING,
                and_(
                    CommentAnalysis.classification_state == STATE_FAILED,
                    CommentAnalysis.next_attempt_at.is_not(None),
                    CommentAnalysis.next_attempt_at <= func.now(),
                ),
            )
        )
        .where(Comment.is_deleted.is_(False))
        # свежие pending раньше созревших ретраев: иначе после сбоя LLM воркер
        # сперва пережёвывает тысячи старых failed, а новое стоит в хвосте
        .order_by(
            sa_case((CommentAnalysis.classification_state == STATE_PENDING, 0), else_=1),
            CommentAnalysis.created_at.asc(),
        )
        .limit(limit)
        .with_for_update(skip_locked=True, of=CommentAnalysis)
    )

    if organization_id is not None:
        q = (
            q.join(
                Publication,
                Publication.id == Comment.publication_id,
            )
            .join(
                PublicSocialLink,
                PublicSocialLink.id == Publication.public_social_link_id,
            )
            .join(
                Public,
                Public.id == PublicSocialLink.public_id,
            )
            .where(Public.organization_id == organization_id)
        )

    rows = (await db.execute(q)).all()

    if not rows:
        return []

    ids = [row.id for row in rows]

    await db.execute(
        update(CommentAnalysis)
        .where(CommentAnalysis.id.in_(ids))
        .values(classification_state=STATE_PROCESSING)
    )

    await db.flush()

    return [
        (
            row.id,
            row.comment_id,
            row.text or "",
        )
        for row in rows
    ]


async def _classify_one(
    text: str,
    *,
    semaphore: asyncio.Semaphore,
) -> tuple[Optional[Any], Optional[str]]:
    """Классифицирует один коммент через LLM под семафором, с ретраями и backoff.

    Возвращает (payload, None) при успехе или (None, error) после исчерпания попыток.
    """

    last_err = ""

    async with semaphore:
        for attempt in range(MAX_LLM_RETRIES + 1):
            try:
                payload = await llm_service.analyze_comment(text)
                return payload, None

            except LLMError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                logger.warning(
                    "LLM classify attempt %d failed: %s",
                    attempt + 1,
                    last_err,
                )
                await asyncio.sleep(0.5 * (attempt + 1))

            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "Unexpected LLM error: %s",
                    last_err,
                )
                break

    return None, last_err or "unknown error"


async def process_pending_batch(
    db: AsyncSession,
    *,
    limit: int = 50,
    organization_id: Optional[UUID] = None,
    concurrency: int = 4,
    apply_analysis: AnalysisPayloadApplier | None = None,
) -> ClassificationStats:
    """Обрабатывает один batch очереди: claim → параллельная LLM-классификация →
    запись результата (done/failed). Возвращает ClassificationStats."""

    if apply_analysis is None:
        apply_analysis = apply_llm_analysis

    stats = ClassificationStats()

    claimed = await _claim_batch(
        db,
        limit=limit,
        organization_id=organization_id,
    )

    if not claimed:
        await db.commit()
        return stats

    stats.picked = len(claimed)

    await db.commit()

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _worker(
        analysis_id: UUID,
        comment_id: UUID,
        text: str,
    ) -> dict[str, Any]:
        started = datetime.now(timezone.utc)

        payload, err = await _classify_one(
            text,
            semaphore=semaphore,
        )

        elapsed_ms = (
            datetime.now(timezone.utc) - started
        ).total_seconds() * 1000.0

        return {
            "analysis_id": analysis_id,
            "comment_id": comment_id,
            "text": text,
            "payload": payload,
            "error": err,
            "elapsed_ms": elapsed_ms,
        }

    results = await asyncio.gather(
        *(
            _worker(analysis_id, comment_id, text)
            for analysis_id, comment_id, text in claimed
        )
    )

    generated_at = datetime.now(timezone.utc)
    geocode_comment_ids: list[UUID] = []

    # Если LLM недоступен целиком, неудачи — не ошибки комментов: возвращаем их
    # в pending без сжигания попыток, воркер встанет в idle до поднятия LLM.
    llm_down = False
    if any(r["payload"] is None for r in results):
        llm_down = not await llm_health.llm_reachable()

    for result in results:
        stats.durations_ms.append(result["elapsed_ms"])

        analysis = (
            await db.execute(
                select(CommentAnalysis).where(
                    CommentAnalysis.id == result["analysis_id"]
                )
            )
        ).scalar_one_or_none()

        if analysis is None:
            stats.skipped += 1
            continue

        if result["payload"] is None:
            if llm_down:
                analysis.classification_state = STATE_PENDING
                stats.skipped += 1
                continue
            register_failed_attempt(analysis, now=generated_at)
            analysis.classification_source = "fallback"
            analysis.summary = (
                analysis.summary or result["text"][:240]
            ).strip()
            analysis.analyzed_at = generated_at
            stats.failed += 1
            continue

        try:
            apply_analysis(
                analysis,
                payload=result["payload"],
                generated_at=generated_at,
                source_text=result["text"],
            )

            analysis.classification_state = STATE_DONE
            analysis.classification_attempts = 0
            analysis.next_attempt_at = None
            stats.succeeded += 1
            geocode_comment_ids.append(result["comment_id"])

        except Exception as exc:
            logger.exception(
                "Failed to apply LLM payload: %s",
                exc,
            )
            register_failed_attempt(analysis, now=generated_at)
            analysis.classification_source = "fallback"
            stats.failed += 1

    await db.commit()

    if geocode_comment_ids:
        try:
            geo_stats = await PainMapService(db).warm_geocode_for_comments(
                geocode_comment_ids,
            )
            if any(int(value or 0) for value in geo_stats.values()):
                logger.info(
                    "Warm geo-cache after classification: considered=%d cached=%d geocoded=%d missed=%d skipped=%d budget_exhausted=%d",
                    geo_stats.get("considered", 0),
                    geo_stats.get("already_cached", 0),
                    geo_stats.get("geocoded", 0),
                    geo_stats.get("missed", 0),
                    geo_stats.get("skipped", 0),
                    geo_stats.get("budget_exhausted", 0),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Warm geo-cache after classification failed: %s", exc)

    logger.info(
        "Worker batch: picked=%d done=%d failed=%d skipped=%d avg=%sms",
        stats.picked,
        stats.succeeded,
        stats.failed,
        stats.skipped,
        stats.to_dict()["avg_ms"],
    )

    return stats


async def process_pending_loop(
    db_factory,
    *,
    organization_id: Optional[UUID] = None,
    batch_size: int = 50,
    idle_sleep_s: float = 5.0,
    concurrency: int = 4,
    stop_event: Optional[asyncio.Event] = None,
) -> None:
    """Бесконечный цикл воркера: берёт батчи из очереди и классифицирует,
    простаивает во время формирования/паузы и при пустой очереди, пока не выставлен stop_event."""

    # На старте ничего реально не в работе — возвращаем осиротевшие после
    # рестарта processing сразу, не дожидаясь 30-мин порога в цикле.
    async with db_factory() as session:
        try:
            await reset_stale_processing(session, older_than_seconds=0)
        except Exception:
            logger.exception("Startup reset of stale 'processing' failed")
        try:
            await reap_ghost_analyses(session, organization_id=organization_id)
        except Exception:
            logger.exception("Startup reap of ghost analyses failed")

    was_idle = False
    dirty = False  # была ли новая классификация с последней авто-пересборки болей
    while True:
        if stop_event is not None and stop_event.is_set():
            return

        # Расчистка зависших идёт ДО проверки простоя: на паузе и во время
        # формирования болей воркер уходит в continue, и раньше записи,
        # застрявшие в processing, не возвращались в очередь вообще.
        async with db_factory() as session:
            try:
                await reset_stale_processing(session)
            except Exception:
                logger.exception("Reset of stale 'processing' failed")

        if worker_should_idle():
            if not was_idle:
                logger.info(
                    "Classification worker idling (%s)",
                    "formation" if is_formation_active() else "paused",
                )
                was_idle = True
            await asyncio.sleep(idle_sleep_s)
            continue

        if was_idle:
            logger.info("Classification worker resumed")
            was_idle = False

        async with db_factory() as session:
            try:
                stats = await process_pending_batch(
                    session,
                    limit=batch_size,
                    organization_id=organization_id,
                    concurrency=concurrency,
                )

            except Exception:
                logger.exception(
                    "Classification worker batch failed"
                )
                stats = ClassificationStats()

        if stats.succeeded:
            dirty = True

        if stats.picked == 0:
            # Брать нечего, но счётчик очереди может быть ненулевым — значит там
            # висят призраки. Гоняем не каждый тик, а только в этот момент:
            # это UPDATE по таблице.
            async with db_factory() as session:
                try:
                    await reap_ghost_analyses(session, organization_id=organization_id)
                except Exception:
                    logger.exception("Reap of ghost analyses failed")

            requeued = 0
            async with db_factory() as session:
                try:
                    requeued = await requeue_low_confidence(session, organization_id=organization_id)
                except Exception:
                    logger.exception("Requeue of low-confidence analyses failed")
            if requeued:
                logger.info("Requeued %d low-confidence analyses for LLM reclassification", requeued)
                continue  # сразу обработать доклассификацию, не засыпая
            if dirty:
                try:
                    await auto_rebuild_snapshots(db_factory)
                except Exception:
                    logger.exception("Auto-rebuild snapshots after drain failed")
                dirty = False
            await asyncio.sleep(idle_sleep_s)

        elif not stats.succeeded:
            # батч прошёл впустую (всё упало или LLM недоступен и записи
            # вернулись в pending) — пауза, чтобы не крутиться вхолостую
            await asyncio.sleep(idle_sleep_s * 2)


__all__ = [
    "STATE_PENDING",
    "STATE_PROCESSING",
    "STATE_DONE",
    "STATE_FAILED",
    "STATE_SKIPPED",
    "SOURCE_LLM_NEEDS_REVIEW",
    "SOURCE_LLM_MANUAL",
    "ClassificationStats",
    "QueuePerformance",
    "estimate_completion_rate",
    "estimate_queue_performance",
    "mark_comment_pending",
    "mark_organization_for_reclassify",
    "reset_stale_processing",
    "reap_ghost_analyses",
    "count_manual_review",
    "list_manual_review",
    "resolve_manual_review",
    "process_pending_batch",
    "process_pending_loop",
]
