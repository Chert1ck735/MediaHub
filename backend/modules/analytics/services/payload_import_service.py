"""Нормализация и импорт внешних payload'ов аналитики."""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import User
from backend.modules.analytics.repositories.snapshot_repository import SnapshotRepository
from backend.modules.analytics.schemas import AnalyticsImportResponse, AnalyticsNormalizeResponse
from backend.modules.analytics.services.payload_helpers import normalize_payload
from backend.modules.analytics.services.snapshot_import_service import SnapshotImportService


class PayloadNormalizeService:
    """Приводит входной payload к канонической схеме без доступа к БД."""

    def normalize(self, source_name: str, payload: dict) -> AnalyticsNormalizeResponse:
        """Возвращает нормализованный payload."""

        return AnalyticsNormalizeResponse(normalized=normalize_payload(source_name, payload))


class PayloadImportService:
    """Импортирует нормализованный payload в snapshot и pain'ы."""

    def __init__(self, db: AsyncSession) -> None:
        self._snapshot_import_service = SnapshotImportService(db)
        self._snapshot_repository = SnapshotRepository(db)

    async def import_global_problem(
        self,
        user: User,
        source_name: str,
        payload: dict,
    ) -> AnalyticsImportResponse:
        """Импортирует snapshot и возвращает API-response."""

        snapshot = await self._snapshot_import_service.import_payload(user, source_name, payload)
        pain_count = await self._snapshot_repository.count_pains(str(snapshot.id))
        return AnalyticsImportResponse(
            snapshot_id=str(snapshot.id),
            source_name=snapshot.source_name,
            source_format=snapshot.source_format,
            pains_imported=pain_count,
            generated_at=snapshot.generated_at.isoformat(),
        )
