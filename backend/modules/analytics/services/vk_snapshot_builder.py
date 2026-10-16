"""Пересборка аналитического снапшота по комментариям VK.

Главный «домашний» сервис аналитики: берёт все VK-комментарии
организации, прогоняет каждый через keyword-правила (а при
``force_reclassify=True`` — через LLM), агрегирует в pain-bucket'ы,
формирует ``StructuredPainAnalyticsPayload``, сохраняет
``AnalysisSnapshot`` + ``Pain`` (с upsert-семантикой) и пересчитывает
``Pain.status`` через ``PainLifecycleService``.

Работа разбита на две фазы, и это принципиально:

* ``classify`` — чтение комментариев + префильтр + LLM. Транзакция чтения
  закрывается ДО первого LLM-вызова, дальше фаза идёт вообще без транзакции.
* ``build`` — бакетирование и persist в короткой write-транзакции
  (``commit`` + ``refresh`` в конце).

Разделять обязательно: LLM-фаза длится десятки минут, и открытая всё это время
транзакция держит ACCESS SHARE на ``comments``/``comment_analysis``. Любой
``ALTER TABLE`` по этим таблицам (например ``ensure_runtime_schema`` на старте
бэкенда) встаёт в очередь за этой блокировкой, а очередь на ACCESS EXCLUSIVE
блокирует и всех последующих читателей — бэкенд не поднимается.

Caller отвечает за предварительный purge старых VK-снапшотов
(``purge_vk_comment_analytics``) — этот шаг живёт отдельно, потому
что вызывается и сам по себе через REST. Purge обязан идти ПОСЛЕ ``classify``:
иначе удалённые снапшоты висят незакоммиченными всю LLM-фазу.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.analysis_snapshots import AnalysisSnapshot
from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.enums import (
    PainStatusEnum,
    RelevanceEnum,
    SentimentEnum,
    SeverityLevelEnum,
)
from backend.db.pain_evidence import PainEvidence
from backend.db.pain_strategies import PainStrategy
from backend.db.pains import Pain
from backend.db.public_social_links import PublicSocialLink
from backend.db.publications import Publication
from backend.db.publics import Public
from backend.db.snapshot_pains import SnapshotPain
from backend.db.social_networks import SocialNetwork
from backend.db.users import User
from backend.app.config import settings
from backend.app.sentry import capture
from backend.modules.analytics.constants import ANALYTICS_NETWORK_CODES
from backend.modules.analytics.dtos.drafts import VkPainDraft
from backend.modules.analytics.mappers.case_mapper import (
    subproblem_to_payload,
    to_message_type_breakdown,
    to_sentiment_breakdown,
)
from backend.modules.analytics.schemas import StructuredPainItem, StructuredPainStrategy, PainCommentExample, \
    StructuredPainAnalyticsPayload
from backend.modules.analytics.services.comment_analysis_service import (
    MESSAGE_TYPES_FOR_COMPLAINT,
    analysis_needs_refresh,
    apply_llm_analysis,
    apply_rule_based_analysis,
    update_subproblem_drafts,
)
from backend.modules.analytics.services.comment_prefilter_service import prefilter_keep_ids
from backend.modules.jobs.services.progress_reporter import ProgressReporter
from backend.modules.jobs.store import JobCancelled, is_cancelled
from backend.modules.analytics.services.pain_lifecycle_service import (
    PainLifecycleService,
)
from backend.modules.analytics.services.payload_helpers import (
    strategy_to_description,
)
from backend.modules.analytics.utils.bucket_helpers import (
    bucket_meta,
    compose_communication_strategy,
    entity_suffix,
    severity_from_bucket,
)
from backend.modules.analytics.utils.category_classifier import (
    normalize_hierarchy_values,
)
from backend.modules.analytics.utils.comment_examples import (
    append_comment_example,
    vk_comment_url,
)
from backend.modules.analytics.utils.official_response import (
    is_community_authored,
    is_meaningful_official_response,
    looks_like_official_response,
)
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    apply_public_social_link_filter,
)
from backend.modules.analytics.utils.sentiment_rules import (
    fallback_relevance,
    has_request_signal,
    looks_sarcastic,
    rule_category_from_topics,
    sentiment_for_text,
    topics_for_text,
)
from backend.modules.analytics.utils.signal_counts import bump_signal_counts
from backend.modules.analytics.utils.text_normalize import (
    append_unique,
    normalized_lookup_text,
    string_dict,
    trim_text,
)
from backend.modules.audit_utils import add_action_log
from backend.modules.llm import service as llm_service
from backend.modules.llm.clients import get_default_llm_model
from backend.modules.metadata_utils import get_or_create_data_source

logger = logging.getLogger(__name__)


@dataclass
class VkClassification:
    """Результат LLM-фазы — всё, что нужно ``build`` для сборки болей.

    Несёт уже загруженные ORM-объекты, чтобы ``build`` не перечитывал их: между
    фазами сессия не держит транзакцию, а ``expire_on_commit=False`` оставляет
    объекты пригодными к использованию и мутации.
    """

    comment_rows: list
    existing_analysis: dict[uuid.UUID, CommentAnalysis]
    preclassified: dict[uuid.UUID, object] = field(default_factory=dict)
    prefilter_dropped: set[uuid.UUID] = field(default_factory=set)
    prefilter_used: bool = False
    started_at: float = field(default_factory=time.perf_counter)


class VkSnapshotBuilder:
    """Полный цикл пересборки VK-снапшота: чтение → анализ → агрегация → persist."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    @staticmethod
    def _merge_buckets(pain_buckets: dict[str, VkPainDraft]) -> dict[str, VkPainDraft]:
        """Сливает бакеты с одинаковой каноничной категорией в один."""
        merged: dict[str, VkPainDraft] = {}
        for bucket in pain_buckets.values():
            key = bucket.category.strip().lower()
            if key in merged:
                existing = merged[key]
                existing.comment_ids |= bucket.comment_ids
                existing.public_ids |= bucket.public_ids
                existing.publication_ids |= bucket.publication_ids
                existing.subproblems |= bucket.subproblems
                existing.requests = list(dict.fromkeys(existing.requests + bucket.requests))[:5]
                existing.negative_points = list(dict.fromkeys(existing.negative_points + bucket.negative_points))[:5]
                existing.evidence.extend(bucket.evidence)
                existing.request_count += bucket.request_count
                existing.complaint_count += bucket.complaint_count
                for sk, sv in bucket.sentiment_counts.items():
                    existing.sentiment_counts[sk] = existing.sentiment_counts.get(sk, 0) + sv
                for mk, mv in bucket.message_type_counts.items():
                    existing.message_type_counts[mk] = existing.message_type_counts.get(mk, 0) + mv
                for sk, si in bucket.subproblem_items.items():
                    if sk not in existing.subproblem_items:
                        existing.subproblem_items[sk] = si
            else:
                merged[key] = bucket
        return merged

    async def _load_comment_rows(self, user: User, since: "datetime | None" = None,
                                 public_social_link_id: PublicSocialLinkFilter = None):
        """Читает неудалённые VK-комментарии организации (строки с метаданными).

        ``since`` ограничивает выборку периодом; ``public_social_link_id`` — площадкой.
        """
        stmt = (
            select(
                Comment,
                Publication.id.label("publication_id"),
                Publication.url.label("publication_url"),
                Public.id.label("public_id"),
                Public.name.label("public_name"),
            )
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
        )
        if since is not None:
            stmt = stmt.where(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        stmt = apply_public_social_link_filter(
            stmt,
            PublicSocialLink.id,
            public_social_link_id,
        )
        stmt = stmt.order_by(Comment.comment_date.asc().nulls_last(), Comment.created_at.asc())
        rows = await self._db.execute(stmt)
        return rows.all()

    async def count_comment_rows(
        self,
        user: User,
        since: "datetime | None" = None,
        public_social_link_id: PublicSocialLinkFilter = None,
    ) -> int:
        """Сколько неудалённых VK-комментариев попадёт в выборку (период + площадка)."""
        stmt = (
            select(func.count())
            .select_from(Comment)
            .join(Publication, Publication.id == Comment.publication_id)
            .join(PublicSocialLink, PublicSocialLink.id == Publication.public_social_link_id)
            .join(SocialNetwork, SocialNetwork.id == PublicSocialLink.social_network_id)
            .join(Public, Public.id == PublicSocialLink.public_id)
            .where(Public.organization_id == user.organization_id)
            .where(SocialNetwork.code.in_(ANALYTICS_NETWORK_CODES))
            .where(Comment.is_deleted.is_(False))
        )
        if since is not None:
            stmt = stmt.where(func.coalesce(Comment.comment_date, Comment.created_at) >= since)
        stmt = apply_public_social_link_filter(
            stmt,
            PublicSocialLink.id,
            public_social_link_id,
        )
        return int(await self._db.scalar(stmt) or 0)

    async def _load_existing_analysis(self, comment_rows) -> dict[uuid.UUID, CommentAnalysis]:
        """Загружает существующий ``CommentAnalysis`` для набора комментариев.

        IN-список чанкуется: asyncpg не принимает больше 32767 параметров.
        """
        comment_ids = [row.Comment.id for row in comment_rows]
        out: dict[uuid.UUID, CommentAnalysis] = {}
        chunk = 20000
        for i in range(0, len(comment_ids), chunk):
            result = await self._db.execute(
                select(CommentAnalysis).where(CommentAnalysis.comment_id.in_(comment_ids[i:i + chunk]))
            )
            for item in result.scalars().all():
                out[item.comment_id] = item
        return out

    async def _recompute_lifecycle(self, snapshot) -> dict[str, int]:
        """Пересчитывает status каждой pain снапшота после rebuild."""
        db = self._db
        lifecycle = PainLifecycleService(db)
        pains = (await db.execute(
            select(Pain)
            .join(SnapshotPain, SnapshotPain.pain_id == Pain.id)
            .where(SnapshotPain.snapshot_id == snapshot.id)
        )).scalars().all()
        statuses = await lifecycle.compute_statuses([pain.id for pain in pains])
        status_transitions: dict[str, int] = {"active": 0, "in_progress": 0, "resolved": 0}
        for pain in pains:
            new_status = statuses.get(pain.id, PainStatusEnum.active)
            if pain.status != new_status:
                pain.status = new_status
            status_transitions[new_status.value] = status_transitions.get(new_status.value, 0) + 1
        return status_transitions

    async def _persist_snapshot(
        self,
        user: User,
        payload: "StructuredPainAnalyticsPayload",
        persisted_links: list,
        generated_at: datetime,
        *,
        progress: "ProgressReporter | None" = None,
    ) -> AnalysisSnapshot:
        """Создаёт снапшот и связанные боли/evidence/comment_pain в БД."""
        db = self._db
        if progress is not None:
            await progress.update(message="Сохранение снапшота…")

        source = await get_or_create_data_source(
            db,
            source_type="api",
            name=payload.source_name,
            description="Автоматическая аналитика комментариев VK",
            configuration={"source_format": payload.source_format, "network": "vk"},
        )

        snapshot_public_id: uuid.UUID | None = None
        all_public_ids = {public_id for _, bucket in persisted_links for public_id in bucket.public_ids}
        if len(all_public_ids) == 1:
            snapshot_public_id = next(iter(all_public_ids))

        snapshot = AnalysisSnapshot(
            organization_id=user.organization_id,
            public_id=snapshot_public_id,
            source_id=source.id,
            source_name=payload.source_name,
            source_format=payload.source_format,
            generated_at=generated_at,
            global_summary=payload.global_summary,
            citizens_requests=payload.citizens_requests,
            dissatisfaction_points=payload.dissatisfaction_points,
            satisfaction_points=payload.satisfaction_points,
            risk_zones=payload.risk_zones,
            quick_wins_30_days=payload.quick_wins_30_days,
            strategic_actions_3_6_months=payload.strategic_actions_3_6_months,
            raw_payload=payload.model_dump(mode="json"),
        )
        db.add(snapshot)
        await db.flush()

        # Переиспользуем боль по (organization, category) — стабильный pain.id между
        # ребилдами (для event_pains и Reaction Gap). Матч по категории, не по public,
        # иначе смена набора пабликов плодит дубли.
        for item, bucket in persisted_links:
            public_id = next(iter(bucket.public_ids)) if len(bucket.public_ids) == 1 else None
            existing_q = (
                select(Pain)
                .where(Pain.organization_id == user.organization_id)
                .where(Pain.category == item.category)
                .order_by(Pain.first_detected_at.asc())
                .limit(1)
            )
            existing_pain = (await db.execute(existing_q)).scalars().first()

            if existing_pain is not None:
                existing_pain.public_id = public_id
                existing_pain.title = item.title
                existing_pain.description = item.description
                existing_pain.mentions_count = item.mentions_count
                existing_pain.severity_level = SeverityLevelEnum(item.severity_level)
                existing_pain.confidence = 0.8
                existing_pain.last_detected_at = generated_at
                # status не трогаем — он мог быть выставлен пользователем как resolved;
                # first_detected_at не трогаем — сохраняем историческую дату.
                pain = existing_pain
            else:
                pain = Pain(
                    organization_id=user.organization_id,
                    public_id=public_id,
                    title=item.title,
                    description=item.description,
                    category=item.category,
                    mentions_count=item.mentions_count,
                    severity_level=SeverityLevelEnum(item.severity_level),
                    status=PainStatusEnum.active,
                    confidence=0.8,
                    first_detected_at=generated_at,
                    last_detected_at=generated_at,
                )
                db.add(pain)
                await db.flush()

            db.add(SnapshotPain(snapshot_id=snapshot.id, pain_id=pain.id))

            if item.strategy and item.strategy.actions:
                db.add(
                    PainStrategy(
                        pain_id=pain.id,
                        description=strategy_to_description(item.strategy),
                        generated_by_llm=False,
                        approved_by_user=False,
                    )
                )

            # дедуп по (pain_id, comment_id) при повторной сборке
            evidence_rows = [
                {
                    "pain_id": pain.id,
                    "publication_id": evidence["publication_id"],
                    "comment_id": evidence["comment_id"],
                    "source_type": "vk_comment",
                    "url": evidence["url"],
                    "note": evidence["note"],
                    "evidence_date": evidence["evidence_date"],
                }
                for evidence in bucket.evidence[:5]
            ]
            if evidence_rows:
                ev_stmt = (
                    pg_insert(PainEvidence)
                    .values(evidence_rows)
                    .on_conflict_do_nothing(index_elements=["pain_id", "comment_id"])
                )
                await db.execute(ev_stmt)

            if bucket.comment_ids:
                cp_rows = [
                    {"comment_id": cid, "pain_id": pain.id, "confidence": 0.8}
                    for cid in bucket.comment_ids
                ]
                cp_stmt = (
                    pg_insert(CommentPain)
                    .values(cp_rows)
                    .on_conflict_do_nothing(index_elements=["comment_id", "pain_id"])
                )
                await db.execute(cp_stmt)

        return snapshot

    @staticmethod
    def _build_payload(
        pain_buckets: dict[str, VkPainDraft],
        comment_rows: list,
        generated_at: datetime,
        citizens_requests: list[str],
        dissatisfaction_points: list[str],
        satisfaction_points: list[str],
    ) -> tuple["StructuredPainAnalyticsPayload", list]:
        """Собирает payload снапшота из бакетов (чистая in-memory трансформация)."""
        # Distinct-счётчик упоминаний по всем бакетам — для relative severity.
        # Через set: мульти-категорийный коммент лежит в нескольких бакетах, sum
        # длин дал бы двойной счёт и занизил долю (а значит и severity).
        all_cids: set = set()
        for b in pain_buckets.values():
            all_cids.update(b.comment_ids)
        total_snapshot_mentions = len(all_cids)

        pains_payload: list[StructuredPainItem] = []
        risk_zones: list[str] = []
        quick_wins: list[str] = []
        strategic_actions: list[str] = []
        persisted_links: list[tuple[StructuredPainItem, VkPainDraft]] = []

        for _, bucket in sorted(
            pain_buckets.items(),
            key=lambda item: len(item[1].comment_ids),
            reverse=True,
        ):
            if not bucket.requests and not bucket.negative_points:
                continue

            meta = bucket_meta(bucket.category, None)
            mentions_count = len(bucket.comment_ids)
            publication_count = len(bucket.publication_ids)
            severity = severity_from_bucket(bucket, total_mentions=total_snapshot_mentions)
            communication_strategy = compose_communication_strategy(meta, bucket.title)
            subproblem_items = [
                subproblem_to_payload(item)
                for _, item in sorted(
                    bucket.subproblem_items.items(),
                    key=lambda pair: len(pair[1].comment_ids),
                    reverse=True,
                )
            ]
            item = StructuredPainItem(
                title=bucket.title,
                # Без описания-повтора: счётчики уже в шапке боли.
                description="",
                category=bucket.category,
                subcategory=None,
                mentions_count=mentions_count,
                publications_count=publication_count,
                severity_level=severity,
                status="active",
                citizens_requests=bucket.requests[:3],
                dissatisfaction_points=bucket.negative_points[:3],
                positive_signals=[],
                sentiment_counts=to_sentiment_breakdown(bucket.sentiment_counts),
                message_type_counts=to_message_type_breakdown(bucket.message_type_counts),
                request_count=bucket.request_count,
                complaint_count=bucket.complaint_count,
                comment_examples=[
                    PainCommentExample.model_validate(example)
                    for example in bucket.comment_examples[:5]
                ],
                complaint_examples=bucket.negative_points[:3],
                request_examples=bucket.requests[:3],
                positive_examples=[],
                subproblems=[item.title for item in subproblem_items[:8]],
                subproblem_items=subproblem_items,
                communication_strategy=communication_strategy,
                evidence_posts=list(
                    dict.fromkeys(item["url"] for item in bucket.evidence if item.get("url"))
                )[:5],
                strategy=StructuredPainStrategy(
                    priority=severity,
                    actions=[communication_strategy],
                ),
            )
            pains_payload.append(item)
            persisted_links.append((item, bucket))
            if severity in {"high", "critical"} and len(risk_zones) < 8:
                risk_zones.append(f"{bucket.title} ({mentions_count} упоминаний)")
            if len(quick_wins) < 8:
                quick_wins.append(meta["quick_win"])
            if len(strategic_actions) < 8:
                strategic_actions.append(meta["strategic"])

        if pains_payload:
            top_titles = ", ".join(item.title for item in pains_payload[:3])
            global_summary = (
                f"LLM-аналитика комментариев VK выявила {len(pains_payload)} устойчивых тем. "
                f"Наиболее заметные боли: {top_titles}."
            )
        elif comment_rows:
            global_summary = (
                "Комментарии VK импортированы, но устойчивые проблемные темы по текущему набору сигналов не выделены."
            )
        else:
            global_summary = "Комментарии VK пока не импортированы или отсутствуют."

        payload = StructuredPainAnalyticsPayload(
            source_name="vk_auto_comments",
            source_format="vk_comment_analytics_v3",
            generated_at=generated_at,
            global_summary=global_summary,
            citizens_requests=list(dict.fromkeys(citizens_requests))[:12],
            dissatisfaction_points=list(dict.fromkeys(dissatisfaction_points))[:12],
            satisfaction_points=list(dict.fromkeys(satisfaction_points))[:12],
            risk_zones=risk_zones,
            quick_wins_30_days=list(dict.fromkeys(quick_wins))[:8],
            strategic_actions_3_6_months=list(dict.fromkeys(strategic_actions))[:8],
            pains=pains_payload,
        )
        return payload, persisted_links

    async def classify(
        self,
        user: User,
        *,
        force_reclassify: bool = False,
        incremental: bool = False,
        since: "datetime | None" = None,
        prefilter: bool = True,
        public_social_link_id: PublicSocialLinkFilter = None,
        progress: "ProgressReporter | None" = None,
    ) -> VkClassification:
        """Фаза 1: читает комментарии и прогоняет их через префильтр + LLM.

        Read-транзакция закрывается ДО первого LLM-вызова и больше не
        открывается до persist'а в ``build``. Это не оптимизация, а условие
        работоспособности: LLM-фаза идёт десятки минут, и открытая транзакция
        всё это время держала бы ACCESS SHARE на ``comments``/``comment_analysis``,
        блокируя любой ``ALTER TABLE`` по ним — вплоть до того, что бэкенд не
        поднимется (``ensure_runtime_schema`` виснет на старте).

        Ничего не пишет в БД: сюда нельзя добавлять запись, не сломав это свойство.
        """
        db = self._db
        started_at = time.perf_counter()
        if progress:
            await progress.update(message="Чтение комментариев из БД…")

        comment_rows = await self._load_comment_rows(user, since, public_social_link_id)
        existing_analysis = await self._load_existing_analysis(comment_rows)

        # Снимаем read-транзакцию перед LLM. expire_on_commit=False, поэтому
        # загруженные объекты остаются пригодны и переиспользуются в build()
        # без повторного SELECT.
        await db.commit()

        result = VkClassification(
            comment_rows=comment_rows,
            existing_analysis=existing_analysis,
            started_at=started_at,
        )

        if progress is not None:
            await progress.update(
                total=len(comment_rows),
                done=0,
                message=f"Обработка {len(comment_rows)} комментариев…",
            )

        # Пред-проход: параллельная LLM-классификация подходящих комментов
        # (семафор ANALYTICS_LLM_CONCURRENCY); цикл в build() только бакетирует
        # из preclassified. Сообщества (from_id<0) и пустой текст не классифицируем.
        preclassified = result.preclassified
        if force_reclassify or incremental:
            eligible: list[tuple[uuid.UUID, str]] = []
            for row in comment_rows:
                c = row.Comment
                t = (c.text or "").strip()
                if not t or is_community_authored(getattr(c, "author_external_id", None)):
                    continue
                if incremental and not force_reclassify and not analysis_needs_refresh(existing_analysis.get(c.id)):
                    continue
                eligible.append((c.id, t))
            if eligible:
                # ── Этап 1/3: дешёвый 3b-префильтр шума (если включён) ──────
                # Отсекает благодарности/спам/флуд на малой модели, чтобы до
                # дорогой 14b доходило меньше комментов. На ошибке 3b коммент
                # остаётся (recall важнее). Тумблер prefilter (UI) + env
                # ANALYTICS_PREFILTER_ENABLED.
                use_prefilter = prefilter and settings.ANALYTICS_PREFILTER_ENABLED
                result.prefilter_used = bool(use_prefilter)
                if use_prefilter:
                    if progress:
                        await progress.update(
                            total=len(eligible), done=0,
                            message=f"Этап 1/3 · префильтр (3b): отсев шума 0/{len(eligible)}…",
                        )
                    pf_t0 = time.perf_counter()

                    async def _pf_progress(done: int, total: int) -> None:
                        if is_cancelled(progress.job_id):
                            raise JobCancelled()
                        el = time.perf_counter() - pf_t0
                        rate = f" · ~{done / el * 60:.0f} комм/мин" if el > 0 else ""
                        await progress.update(
                            done=done,
                            message=f"Этап 1/3 · префильтр (3b): отсев шума {done}/{total}{rate}…",
                        )

                    keep_ids = await prefilter_keep_ids(
                        eligible, on_progress=_pf_progress if progress else None
                    )
                    to_llm = [(cid, t) for cid, t in eligible if cid in keep_ids]
                    result.prefilter_dropped = {cid for cid, _ in eligible if cid not in keep_ids}
                else:
                    to_llm = list(eligible)

                # ── Этап 2/3: 14b ─────────────────────────────────────────
                if progress:
                    await progress.update(
                        total=max(1, len(to_llm)), done=0,
                        message=(
                            f"Этап 2/3 · LLM-классификация {len(to_llm)} из "
                            f"{len(eligible)} (шум отсеян: {len(result.prefilter_dropped)})…"
                        ),
                    )
                llm_t0 = time.perf_counter()
                sem = asyncio.Semaphore(max(1, int(getattr(settings, "ANALYTICS_LLM_CONCURRENCY", 4))))
                model_name = get_default_llm_model()

                # Сбои LLM копим, а не шлём по одному: если модель лежит, тысяча
                # комментариев дала бы тысячу одинаковых событий в Sentry и
                # утопила бы в них всё остальное. Отправим одно, со сводкой.
                llm_failures: list[Exception] = []

                async def _classify(cid: uuid.UUID, body: str):
                    async with sem:
                        try:
                            payload = await llm_service.analyze_comment(body, model=model_name)
                        except Exception as exc:  # noqa: BLE001 — сбой → fallback на правила
                            llm_failures.append(exc)
                            payload = None
                        return cid, payload

                tasks = [asyncio.create_task(_classify(cid, t)) for cid, t in to_llm]
                completed = 0
                for fut in asyncio.as_completed(tasks):
                    cid, payload = await fut
                    preclassified[cid] = payload
                    completed += 1
                    if progress and (completed % 5 == 0 or completed == len(to_llm)):
                        if is_cancelled(progress.job_id):
                            for pending in tasks:
                                pending.cancel()
                            raise JobCancelled()
                        el = time.perf_counter() - llm_t0
                        rate = f" · ~{completed / el * 60:.0f} комм/мин" if el > 0 else ""
                        await progress.update(
                            done=completed,
                            message=f"Этап 2/3 · LLM-классификация {completed}/{len(to_llm)}{rate}…",
                        )

                # Одно событие на всю пересборку, а не на каждый коммент.
                if llm_failures:
                    logger.error(
                        "LLM не ответил на %d из %d комментариев — они ушли на "
                        "правила. Классификация будет заметно хуже.",
                        len(llm_failures),
                        len(to_llm),
                    )
                    capture(
                        llm_failures[0],
                        llm_failed=len(llm_failures),
                        llm_total=len(to_llm),
                        llm_model=model_name,
                    )
            if progress:
                await progress.update(
                    total=len(comment_rows), done=0, message="Этап 3/3 · сборка болей…",
                )

        return result

    async def build(
        self,
        user: User,
        *,
        force_reclassify: bool = False,
        incremental: bool = False,
        since: "datetime | None" = None,
        prefilter: bool = True,
        public_social_link_id: PublicSocialLinkFilter = None,
        progress: "ProgressReporter | None" = None,
        classification: VkClassification | None = None,
    ) -> tuple[AnalysisSnapshot, dict[str, int]]:
        """Фаза 2: бакетирует комментарии в боли и сохраняет ``AnalysisSnapshot``.

        Возвращает снапшот + статистику reclassify. Транзакция управляется
        внутри: финальный ``commit`` и ``refresh``.

        ``classification`` — результат ``classify``. Штатно его передаёт
        ``AnalyticsRefreshService``, который вызывает ``classify`` ДО purge,
        чтобы длинная LLM-фаза не держала открытой транзакцию с удалёнными
        снапшотами. Если не передан — ``build`` классифицирует сам (для прямых
        вызовов и тестов); в этом случае всё так же безопасно, потому что
        ``classify`` сам закрывает read-транзакцию перед LLM.
        """
        db = self._db
        if classification is None:
            classification = await self.classify(
                user,
                force_reclassify=force_reclassify,
                incremental=incremental,
                since=since,
                prefilter=prefilter,
                public_social_link_id=public_social_link_id,
                progress=progress,
            )

        comment_rows = classification.comment_rows
        existing_analysis = classification.existing_analysis
        preclassified = classification.preclassified
        prefilter_dropped = classification.prefilter_dropped

        generated_at = datetime.now(timezone.utc)
        pain_buckets: dict[str, VkPainDraft] = {}
        citizens_requests: list[str] = []
        dissatisfaction_points: list[str] = []
        satisfaction_points: list[str] = []
        reclassify_stats = {
            "reclassified_comments": 0,
            "llm_classified_comments": 0,
            "fallback_classified_comments": 0,
        }

        for _idx, row in enumerate(comment_rows, start=1):
            # Отмену И прогресс обновляем в начале КАЖДОЙ итерации, до любых
            # continue. При force_reclassify=True каждый коммент уходит в LLM
            # ещё до фильтров, но большинство потом вылетает по continue
            # (нерелевантный/оффтоп/офиц.ответ/благодарность/дедуп) — если
            # репортить done внизу, счётчик замирает (10/1662), пока Ollama
            # уже намолотила сотни. Поэтому done=_idx идёт по фактически
            # обработанным комментам и совпадает с активностью Ollama.
            if progress and is_cancelled(progress.job_id):
                raise JobCancelled()
            if progress:
                await progress.update(
                    done=_idx,
                    message=(
                        f"Комментарий {_idx}/{len(comment_rows)} · "
                        f"LLM: {reclassify_stats['llm_classified_comments']} · "
                        f"fallback: {reclassify_stats['fallback_classified_comments']}"
                    ),
                )

            comment = row.Comment
            if comment.id in prefilter_dropped:
                continue  # 3b-префильтр отсёк как шум — мимо 14b и бакетов
            text = (comment.text or "").strip()
            if not text:
                continue

            rule_topics = topics_for_text(text)
            rule_sentiment = sentiment_for_text(text)
            rule_has_request = has_request_signal(text)
            rule_is_sarcasm = looks_sarcastic(text)
            if rule_is_sarcasm:
                rule_sentiment = SentimentEnum.negative
            rule_relevance = fallback_relevance(rule_topics, rule_has_request, rule_sentiment)

            analysis = existing_analysis.get(comment.id)
            if analysis is None:
                analysis = CommentAnalysis(comment_id=comment.id)
                db.add(analysis)

            # Детерминированно отсекаем комментарии от самого паблика/сообщества
            # (from_id < 0): это ответы модератора/организации, а не сообщения пользователей о проблемах.
            # Делаем ДО классификации — не тратим LLM-вызов и не пускаем их
            # в бакеты/примеры/счётчики.
            if is_community_authored(getattr(comment, "author_external_id", None)):
                analysis.author_type = "official"
                analysis.is_official_response = is_meaningful_official_response(text)
                analysis.relevance = RelevanceEnum.irrelevant
                if not str(getattr(analysis, "message_type", "") or "").strip():
                    analysis.message_type = "offtopic"
                continue

            needs_refresh = analysis_needs_refresh(analysis)
            if force_reclassify or needs_refresh:
                reclassify_stats["reclassified_comments"] += 1
                llm_payload = preclassified.get(comment.id)
                if llm_payload is not None:
                    apply_llm_analysis(
                        analysis,
                        payload=llm_payload,
                        generated_at=generated_at,
                        source_text=text,
                    )
                    reclassify_stats["llm_classified_comments"] += 1
                elif str(getattr(analysis, "classification_source", "") or "") in {"llm", "llm_other", "llm_manual"}:
                    pass  # LLM недоступен — не понижаем уже хорошую классификацию до rule-based
                else:
                    apply_rule_based_analysis(
                        analysis,
                        text=text,
                        generated_at=generated_at,
                        rule_topics=rule_topics,
                        rule_sentiment=rule_sentiment,
                        rule_has_request=rule_has_request,
                        author_name=comment.author_name,
                    )
                    reclassify_stats["fallback_classified_comments"] += 1

            sentiment = analysis.sentiment or rule_sentiment
            relevance = analysis.relevance or rule_relevance
            hierarchy = string_dict(getattr(analysis, "hierarchy", None))
            entities = string_dict(getattr(analysis, "entities", None))
            author_type = str(getattr(analysis, "author_type", "") or "citizen").strip().lower()
            message_type = str(getattr(analysis, "message_type", "") or "").strip().lower()
            is_official_response = bool(getattr(analysis, "is_official_response", False))
            # текстовую эвристику применяем только к rule/low-confidence, LLM не перебиваем
            if (str(getattr(analysis, "classification_source", "") or "") not in {"llm", "llm_other", "llm_manual"}
                    and looks_like_official_response(text, comment.author_name)):
                analysis.author_type = "official"
                analysis.is_official_response = True
                analysis.relevance = RelevanceEnum.irrelevant
                continue

            if not message_type:
                if rule_is_sarcasm:
                    # сарказм — тон, а не тип сообщения
                    message_type = "complaint"
                elif rule_has_request:
                    message_type = "request"
                elif sentiment == SentimentEnum.negative:
                    message_type = "complaint"
                elif sentiment == SentimentEnum.positive:
                    message_type = "gratitude"
                else:
                    message_type = "offtopic"

            if relevance != RelevanceEnum.relevant:
                continue
            if is_official_response or author_type in {"admin", "official"}:
                continue
            if message_type == "offtopic":
                continue

            category, subcategory, case_name = normalize_hierarchy_values(
                category=hierarchy.get("category", "").strip(),
                subcategory=hierarchy.get("subcategory", "").strip(),
                case_name=hierarchy.get("case", "").strip(),
                source_text=text,
            )
            analysis.hierarchy = {
                "category": category,
                "subcategory": subcategory,
                "case": case_name,
            }
            summary_text = trim_text(
                str(getattr(analysis, "summary", None) or case_name or text),
                180,
            )
            signal_text = f"{summary_text}{entity_suffix(entities)}"

            if message_type == "request":
                append_unique(citizens_requests, signal_text, 12)
            if sentiment == SentimentEnum.negative or message_type in {"complaint", "sarcasm"}:
                append_unique(dissatisfaction_points, signal_text, 12)
            if message_type == "gratitude" and sentiment == SentimentEnum.positive:
                append_unique(satisfaction_points, signal_text, 12)
                continue

            # В боль идут только жалобы/сарказм/запросы — благодарность и похвала
            # (любой тональности) болью не считаются и в категории не попадают.
            if message_type not in {"complaint", "sarcasm", "request"}:
                continue

            # В какую боль (pain bucket) уходит комментарий:
            #   - если category известна — кладём в её bucket;
            #   - если category пустая, но keyword-правила дали тему — берём её;
            #   - иначе пропускаем: комментарий останется в глобальной сводке,
            #     но не породит отдельной «боли Другое» в топе.
            bucket_category = category or rule_category_from_topics(rule_topics)
            if not bucket_category or bucket_category == "Другое":
                continue

            meta = bucket_meta(bucket_category, None)
            bucket_key = bucket_category.strip().lower()
            bucket = pain_buckets.setdefault(
                bucket_key,
                VkPainDraft(
                    topic=bucket_key,
                    title=meta["category"],
                    category=meta["category"],
                ),
            )
            # R2. Дедупликация копипасты — сравниваем по первым 120 символам
            # нормализованного текста. Дубль пропускаем полностью.
            text_key = normalized_lookup_text(text)[:120]
            if text_key and text_key in bucket.seen_text_hashes:
                continue
            if text_key:
                bucket.seen_text_hashes.add(text_key)

            bucket.comment_ids.add(comment.id)
            bucket.public_ids.add(row.public_id)
            bucket.publication_ids.add(row.publication_id)
            # R6. Гистограмма часов для best-post-time recommendation.
            cdt = comment.comment_date or comment.created_at
            if cdt is not None:
                bucket.hourly_histogram[cdt.hour] = bucket.hourly_histogram.get(cdt.hour, 0) + 1
            bump_signal_counts(
                bucket.sentiment_counts,
                bucket.message_type_counts,
                sentiment=sentiment,
                message_type=message_type,
            )
            if message_type == "request":
                bucket.request_count += 1
            if message_type in MESSAGE_TYPES_FOR_COMPLAINT:
                bucket.complaint_count += 1

            if subcategory:
                bucket.subproblems.add(subcategory)
            if case_name:
                bucket.subproblems.add(
                    f"{subcategory}: {case_name}" if subcategory else case_name
                )

            example_url = vk_comment_url(row.publication_url, comment.external_id)
            if row.publication_url:
                bucket.evidence.append(
                    {
                        "publication_id": row.publication_id,
                        "comment_id": comment.id,
                        "url": example_url or row.publication_url,
                        "note": trim_text(text, 320),
                        "evidence_date": comment.comment_date or comment.created_at,
                    }
                )

            append_comment_example(
                bucket,
                text=text,
                message_type=message_type,
                sentiment=sentiment,
                publication_url=row.publication_url,
                comment_external_id=comment.external_id,
                comment_id=comment.id,
            )
            update_subproblem_drafts(
                bucket,
                subcategory=subcategory,
                case_name=case_name,
                text=text,
                message_type=message_type,
                sentiment=sentiment,
                publication_url=row.publication_url,
                comment_external_id=comment.external_id,
                comment_id=comment.id,
                publication_id=row.publication_id,
            )

            if message_type == "request":
                append_unique(bucket.requests, signal_text, 5)
            if sentiment == SentimentEnum.negative or message_type in {"complaint", "sarcasm"}:
                append_unique(bucket.negative_points, signal_text, 5)

        if progress:
            await progress.update(done=len(comment_rows), message="Сборка снапшота…")

        if progress is not None:
            await progress.update(
                done=len(comment_rows),
                message="Сборка снапшота…",
            )

        # Сливаем бакеты с одинаковой каноничной категорией в один.
        pain_buckets = self._merge_buckets(pain_buckets)

        payload, persisted_links = self._build_payload(
            pain_buckets,
            comment_rows,
            generated_at,
            citizens_requests,
            dissatisfaction_points,
            satisfaction_points,
        )

        snapshot = await self._persist_snapshot(
            user, payload, persisted_links, generated_at, progress=progress
        )

        status_transitions = await self._recompute_lifecycle(snapshot)

        if progress is not None:
            await progress.update(message="Пересчёт статусов болей…")

        add_action_log(
            db,
            user_id=user.id,
            action="vk_comment_snapshot_rebuilt",
            entity_type="analysis_snapshot",
            entity_id=snapshot.id,
            details={
                "source_name": payload.source_name,
                "source_format": payload.source_format,
                "pains_count": len(payload.pains),
                "comment_rows": len(comment_rows),
                "pain_status_distribution": status_transitions,
                **reclassify_stats,
            },
        )
        await db.commit()
        await db.refresh(snapshot)

        # elapsed считаем от начала classify — это то, сколько ждал пользователь.
        elapsed = time.perf_counter() - classification.started_at
        processed = (
            reclassify_stats["llm_classified_comments"]
            + reclassify_stats["fallback_classified_comments"]
        )
        reclassify_stats["elapsed_seconds"] = round(elapsed, 1)
        reclassify_stats["comments_per_min"] = round(processed / elapsed * 60) if elapsed > 0 else 0
        # Берём фактический флаг из classify: префильтр работает и при
        # incremental, а не только при force_reclassify.
        reclassify_stats["prefilter_used"] = classification.prefilter_used
        reclassify_stats["prefilter_dropped"] = len(prefilter_dropped)

        if progress is not None:
            await progress.update(
                done=len(comment_rows),
                message="VK-снапшот пересобран",
            )

        return snapshot, reclassify_stats
