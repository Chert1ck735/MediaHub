"""Сервис формирования summary analytics без бизнес-логики в router."""

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.repositories.publication_repository import PublicationRepository
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import AnalyticsSummaryResponse, SlaStats
from backend.modules.analytics.services.pain_slice_service import PainSliceService
from backend.modules.analytics.services.snapshot_signals_service import SnapshotSignalsService
from backend.modules.analytics.utils.interfaces import SnapshotSignalsServiceProtocol, SnapshotRepositoryProtocol, \
    PublicationRepositoryProtocol
from backend.modules.analytics.utils.time_helpers import period_to_since
from backend.modules.analytics.utils.public_link_filter import (
    compact_public_social_link_filter,
    parse_public_social_link_ids,
)


class AnalyticsSummaryService:
    """Собирает ответ /summary из snapshot, signals и pain count."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        snapshot_repository: SnapshotRepositoryProtocol | None = None,
        publication_repository: PublicationRepositoryProtocol | None = None,
        signals_service: SnapshotSignalsServiceProtocol | None = None,
    ):
        self._db = db
        self._snapshot_repository = snapshot_repository or SnapshotRepository(db)
        self._publication_repository = publication_repository or PublicationRepository(db)
        self._signals_service = signals_service or SnapshotSignalsService(db)
        self._comment_repository = CommentRepository(db)
        self._slice_service = PainSliceService(db)

    async def get_summary(
        self,
        user: User,
        *,
        period: str = "all",
        public_social_link_id: str | None = None,
        municipality_name: str | None = None,
    ) -> AnalyticsSummaryResponse:
        """Возвращает summary текущего VK snapshot'а."""

        snapshot = await self._snapshot_repository.get_latest_vk(user)
        if snapshot is None:
            raise ValueError("Аналитическая выгрузка не найдена")

        link_ids = parse_public_social_link_ids(public_social_link_id)
        link_filter = compact_public_social_link_filter(link_ids)
        since = period_to_since(period)
        platforms = await self._publication_repository.list_vk_public_names(user)
        count_kwargs = {"since": since, "link_id": link_filter}
        if municipality_name is not None:
            count_kwargs["municipality_name"] = municipality_name
        counts = await self._signals_service.get_counts(str(snapshot.id), user, **count_kwargs)
        try:
            sla_kwargs = {"since": since, "link_id": link_filter}
            if municipality_name is not None:
                sla_kwargs["municipality_name"] = municipality_name
            sla = await self._comment_repository.sla_stats(user, **sla_kwargs)
        except Exception:  # SLA — вторичная метрика, её сбой не должен рушить summary
            sla = {}
        pains = await self._snapshot_repository.list_pains(str(snapshot.id))
        if municipality_name is not None:
            live_mentions = await self._slice_service.count_mentions(
                [pain.id for pain in pains],
                since=since,
                link_id=link_filter,
                municipality_name=municipality_name,
            )
            pain_count = sum(1 for count in live_mentions.values() if int(count or 0) > 0)
        elif link_filter is None:
            pain_count = await self._snapshot_repository.count_pains(str(snapshot.id))
        else:
            pain_count = await self._snapshot_repository.count_filtered_pains(
                str(snapshot.id), link_filter, since=since
            )

        return AnalyticsSummaryResponse(
            snapshot_id=str(snapshot.id),
            generated_at=snapshot.generated_at.isoformat(),
            global_summary=snapshot.global_summary,
            source_label="Соцсети" if snapshot.source_name == "vk_auto_comments" else snapshot.source_name,
            platforms=platforms,
            pain_count=pain_count,
            total_comment_count=int(counts.get("total_comments", 0)),
            classified_comment_count=int(counts.get("classified_comments", 0)),
            relevant_comment_count=counts["relevant_comments"],
            complaint_count=counts["complaints"],
            request_count=counts["requests"],
            appeal_count=counts["appeals"],
            gratitude_count=counts["gratitude"],
            other_count=counts["other"],
            filtered_count=counts["filtered"],
            unclassified_count=int(counts.get("unclassified_count", 0)),
            recommended_post_window=counts.get("recommended_post_window"),
            top_pains=[pain.title for pain in pains[:5]],
            sentiment_breakdown=counts["sentiment_breakdown"],
            message_type_breakdown=counts["message_type_breakdown"],
            relevance_breakdown=counts["relevance_breakdown"],
            category_breakdown=counts["category_breakdown"],
            sla=SlaStats(**sla) if sla else SlaStats(),
        )
