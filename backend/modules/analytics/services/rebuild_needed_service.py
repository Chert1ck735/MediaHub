"""Проверка необходимости пересборки VK-аналитики."""
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.comment_repository import CommentRepository
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import RebuildNeededResponse


# Пересобирать чаще этого нет смысла: комментарии капают непрерывно, а
# пересборка проходит по всей базе.
_MIN_INTERVAL = timedelta(minutes=15)


class RebuildNeededService:
    """Решает, нужен ли новый VK snapshot перед refetch frontend'а."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        snapshot_repository: SnapshotRepository | None = None,
        comment_repository: CommentRepository | None = None,
    ) -> None:
        self._db = db
        self._snapshot_repository = snapshot_repository or SnapshotRepository(db)
        self._comment_repository = comment_repository or CommentRepository(db)

    async def check(self, user: User) -> RebuildNeededResponse:
        """Возвращает флаг пересборки и причину."""
        snapshot = await self._snapshot_repository.get_latest_vk(user)
        if snapshot is None:
            new_comments = await self._comment_repository.count_org_comments(user)
            return RebuildNeededResponse(
                needs_rebuild=new_comments > 0,
                reason="no_snapshot" if new_comments > 0 else "no_data",
                new_comments=new_comments,
            )

        new_comments = await self._comment_repository.count_org_comments(
            user, since=snapshot.generated_at
        )
        pending = await self._comment_repository.count_unanalyzed_comments(user)

        generated_at = snapshot.generated_at
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        too_soon = datetime.now(timezone.utc) - generated_at < _MIN_INTERVAL

        if new_comments > 0:
            reason = "new_comments"
        elif pending > 0:
            reason = "pending_classification"
        else:
            reason = "up_to_date"

        # Ждущие классификации сами по себе поводом не являются: пересборка
        # только агрегирует уже размеченное, очередь разбирает фоновый воркер.
        # Иначе при непустой очереди страница пересобирала снапшот при каждом
        # открытии, а очередь от этого не уменьшалась.
        return RebuildNeededResponse(
            needs_rebuild=new_comments > 0 and not too_soon,
            reason=reason,
            new_comments=new_comments,
            pending_classification=pending,
        )
