"""Пересборка VK-аналитики без фасада analytics.service."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User, AnalysisSnapshot
from backend.modules.analytics.llm_coordination import formation_started, formation_finished
from backend.modules.analytics.services.vk_snapshot_purge_service import VkSnapshotPurgeService
from backend.modules.analytics.utils.interfaces import VkSnapshotPurgeServiceProtocol, VkSnapshotBuilderProtocol
from backend.modules.analytics.services.vk_snapshot_builder import VkSnapshotBuilder
from backend.modules.analytics.utils.public_link_filter import PublicSocialLinkFilter


class AnalyticsRefreshService:
    """Очищает старые VK snapshot'ы и запускает независимый build-сервис."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        purge_service: VkSnapshotPurgeServiceProtocol | None = None,
        snapshot_builder: VkSnapshotBuilderProtocol | None = None,
    ):
        self._db = db
        self._purge_service = purge_service or VkSnapshotPurgeService(db)
        self._snapshot_builder = snapshot_builder or VkSnapshotBuilder(db)

    async def refresh(
        self,
        user: User,
        *,
        force_reclassify: bool = False,
        incremental: bool = False,
        since: datetime | None = None,
        prefilter: bool = True,
        public_social_link_id: PublicSocialLinkFilter = None,
        progress=None,
    ) -> tuple[AnalysisSnapshot, dict[str, int]]:
        """Удаляет старые VK snapshot'ы и возвращает новый snapshot со статистикой."""

        uses_llm = force_reclassify or incremental
        if uses_llm:
            formation_started()
        try:
            # Порядок фаз менять нельзя: сначала classify (LLM, десятки минут,
            # без открытой транзакции), потом короткая запись. Если запись идёт
            # первой, её блокировки висят всю LLM-фазу, ALTER TABLE встаёт в
            # очередь и бэкенд не проходит ensure_runtime_schema при старте.
            classification = await self._snapshot_builder.classify(
                user,
                force_reclassify=force_reclassify,
                incremental=incremental,
                since=since,
                prefilter=prefilter,
                public_social_link_id=public_social_link_id,
                progress=progress,
            )
            previous_pain_ids = await self._purge_service.purge_all_snapshots(user)
            snapshot, stats = await self._snapshot_builder.build(
                user,
                force_reclassify=force_reclassify,
                incremental=incremental,
                since=since,
                prefilter=prefilter,
                public_social_link_id=public_social_link_id,
                progress=progress,
                classification=classification,
            )
            await self._purge_service.delete_orphan_pains(snapshot.id, previous_pain_ids)
            return snapshot, stats
        finally:
            if uses_llm:
                formation_finished()
