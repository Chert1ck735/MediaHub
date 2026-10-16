"""Доступ к данным аналитических снапшотов и их связей с болями.

Репозиторий отвечает за SQL — выборки и счётчики по таблицам
``AnalysisSnapshot`` и ``SnapshotPain``. Транзакциями он не управляет
(``commit``/``rollback`` остаётся на стороне сервиса).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.analysis_snapshots import AnalysisSnapshot
from backend.db.comment_analysis import CommentAnalysis
from backend.db.comment_pains import CommentPain
from backend.db.comments import Comment
from backend.db.pains import Pain
from backend.db.publications import Publication
from backend.db.snapshot_pains import SnapshotPain
from backend.db.users import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.utils.public_link_filter import (
    PublicSocialLinkFilter,
    apply_public_social_link_filter,
)


class SnapshotRepository:
    """SQL-доступ к ``AnalysisSnapshot`` и ``SnapshotPain``."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_latest(self, user: User) -> AnalysisSnapshot | None:
        """Возвращает самый свежий снапшот организации (без фильтра по источнику)."""

        result = await self._db.execute(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.organization_id == user.organization_id)
            .order_by(
                AnalysisSnapshot.generated_at.desc(),
                AnalysisSnapshot.created_at.desc(),
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_vk(self, user: User) -> AnalysisSnapshot | None:
        """Свежий VK-снапшот с fallback на любой свежий снапшот организации."""

        result = await self._db.execute(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.organization_id == user.organization_id)
            .where(AnalysisSnapshot.source_name == "vk_auto_comments")
            .order_by(
                AnalysisSnapshot.generated_at.desc(),
                AnalysisSnapshot.created_at.desc(),
            )
            .limit(1)
        )
        snapshot = result.scalar_one_or_none()
        if snapshot is not None:
            return snapshot
        return await self.get_latest(user)

    async def list_pains(self, snapshot_id: str) -> list[Pain]:
        """Список болей снапшота, отсортированный по числу упоминаний."""

        snapshot_uuid = uuid.UUID(snapshot_id)
        result = await self._db.execute(
            select(Pain)
            .join(SnapshotPain, SnapshotPain.pain_id == Pain.id)
            .where(SnapshotPain.snapshot_id == snapshot_uuid)
            .order_by(Pain.mentions_count.desc(), Pain.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_pains(self, snapshot_id: str) -> int:
        """Количество болей, привязанных к снапшоту."""

        snapshot_uuid = uuid.UUID(snapshot_id)
        result = await self._db.execute(
            select(func.count())
            .select_from(SnapshotPain)
            .where(SnapshotPain.snapshot_id == snapshot_uuid)
        )
        return int(result.scalar() or 0)

    async def list_vk_snapshots(self, user: User) -> list[AnalysisSnapshot]:
        """Все VK-снапшоты организации (для purge-сценария)."""

        result = await self._db.execute(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.organization_id == user.organization_id)
            .where(AnalysisSnapshot.source_name == "vk_auto_comments")
        )
        return list(result.scalars().all())

    async def count_filtered_pains(
        self,
        snapshot_id: str,
        link_id: PublicSocialLinkFilter,
        *,
        since: datetime | None = None,
    ) -> int:
        """Число pain'ов снапшота, у которых есть обращения данной площадки/периода.

        Скоуп и дата — те же, что в списке болей, иначе pain_count в summary
        расходится с числом карточек.
        """

        stmt = CommentRepository.appeal_scope(
            select(func.count(func.distinct(Pain.id)))
            .select_from(Pain)
            .join(SnapshotPain, SnapshotPain.pain_id == Pain.id)
            .join(CommentPain, CommentPain.pain_id == Pain.id)
            .join(Comment, Comment.id == CommentPain.comment_id)
            .join(CommentAnalysis, CommentAnalysis.comment_id == Comment.id)
            .join(Publication, Publication.id == Comment.publication_id)
            .where(SnapshotPain.snapshot_id == uuid.UUID(snapshot_id))
            .where(Comment.is_deleted.is_(False))
        )
        stmt = apply_public_social_link_filter(
            stmt,
            Publication.public_social_link_id,
            link_id,
        )
        if since is not None:
            stmt = stmt.where(
                func.coalesce(Comment.comment_date, Comment.created_at) >= since
            )
        return int((await self._db.execute(stmt)).scalar() or 0)

    async def list_pain_ids_for_snapshots(
        self,
        snapshot_ids: list[uuid.UUID],
    ) -> list[uuid.UUID]:
        """Уникальные id болей, связанных с указанными снапшотами."""

        if not snapshot_ids:
            return []
        result = await self._db.execute(
            select(SnapshotPain.pain_id).where(SnapshotPain.snapshot_id.in_(snapshot_ids))
        )
        return list(dict.fromkeys(row[0] for row in result.all()))
