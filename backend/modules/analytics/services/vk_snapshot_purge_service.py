"""Сервис очистки VK snapshot'ов."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User, Pain
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.utils.interfaces import SnapshotRepositoryProtocol


class VkSnapshotPurgeService:
    """Удаляет VK snapshot'ы организации; боли переживают пересборку."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        snapshot_repository: SnapshotRepositoryProtocol | None = None,
    ) -> None:
        self._db = db
        self._snapshot_repository = snapshot_repository or SnapshotRepository(db)

    async def purge_all_snapshots(self, user: User) -> list[uuid.UUID]:
        """Удаляет VK snapshot'ы, но не боли (их переиспользует build), и
        возвращает id прежних болей для последующей очистки сирот."""
        snapshots = await self._snapshot_repository.list_vk_snapshots(user)
        if not snapshots:
            return []

        snapshot_ids = [snapshot.id for snapshot in snapshots]
        pain_ids = await self._snapshot_repository.list_pain_ids_for_snapshots(snapshot_ids)

        for snapshot in snapshots:
            await self._db.delete(snapshot)

        await self._db.flush()
        return pain_ids

    async def delete_orphan_pains(
        self,
        snapshot_id: uuid.UUID,
        previous_pain_ids: list[uuid.UUID],
    ) -> None:
        """Удаляет из previous_pain_ids боли, не подтверждённые в новом снапшоте
        (скоуп ограничен ими, чтобы не задеть импортированные/не-VK боли)."""
        if not previous_pain_ids:
            return

        current = set(
            await self._snapshot_repository.list_pain_ids_for_snapshots([snapshot_id])
        )
        orphan_ids = [pid for pid in previous_pain_ids if pid not in current]
        if not orphan_ids:
            return

        pains_result = await self._db.execute(select(Pain).where(Pain.id.in_(orphan_ids)))
        for pain in pains_result.scalars().all():
            await self._db.delete(pain)

        await self._db.commit()
