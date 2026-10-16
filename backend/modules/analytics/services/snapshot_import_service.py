"""
Импорт внешнего payload-а в виде ``AnalysisSnapshot`` с привязанными болями.

Сервис принимает сырой словарь (legacy или новый формат), приводит его к
канонической схеме и сохраняет:

  * ``AnalysisSnapshot`` — основной agg-объект со всеми списками;
  * ``Pain`` + ``SnapshotPain`` — по одной записи на каждый pain;
  * ``PainEvidence`` — для evidence-постов;
  * ``PainStrategy`` — если в payload-е была стратегия.

Транзакция управляется здесь: ``await db.commit()`` в конце, ``refresh``
для возврата актуального состояния. Caller получает готовый
``AnalysisSnapshot`` или исключение БД, если что-то упало.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.analysis_snapshots import AnalysisSnapshot
from backend.db.enums import PainStatusEnum, SeverityLevelEnum
from backend.db.pain_evidence import PainEvidence
from backend.db.pain_strategies import PainStrategy
from backend.db.pains import Pain
from backend.db.snapshot_pains import SnapshotPain
from backend.db.users import User
from backend.modules.analytics.services.payload_helpers import (
    infer_snapshot_source_type,
    normalize_payload,
    strategy_to_description,
)
from backend.modules.audit_utils import add_action_log
from backend.modules.metadata_utils import get_or_create_data_source


class SnapshotImportService:
    """Принимает payload и сохраняет ``AnalysisSnapshot`` со связанными болями."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def import_payload(
        self,
        user: User,
        source_name: str,
        payload: dict[str, Any],
    ) -> AnalysisSnapshot:
        """Полный цикл импорта: нормализация → snapshot → pains → audit-log → commit."""

        normalized = normalize_payload(source_name, payload)
        source = await get_or_create_data_source(
            self._db,
            source_type=infer_snapshot_source_type(
                normalized.source_name, normalized.source_format
            ),
            name=normalized.source_name,
            description="Источник аналитического snapshot по болям",
            configuration={"source_format": normalized.source_format},
        )

        snapshot = AnalysisSnapshot(
            organization_id=user.organization_id,
            source_id=source.id,
            source_name=normalized.source_name,
            source_format=normalized.source_format,
            generated_at=normalized.generated_at or datetime.now(timezone.utc),
            global_summary=normalized.global_summary,
            citizens_requests=normalized.citizens_requests,
            dissatisfaction_points=normalized.dissatisfaction_points,
            satisfaction_points=normalized.satisfaction_points,
            risk_zones=normalized.risk_zones,
            quick_wins_30_days=normalized.quick_wins_30_days,
            strategic_actions_3_6_months=normalized.strategic_actions_3_6_months,
            raw_payload=normalized.model_dump(mode="json"),
        )
        self._db.add(snapshot)
        await self._db.flush()

        for item in normalized.pains:
            pain = Pain(
                organization_id=user.organization_id,
                title=item.title,
                description=item.description,
                category=item.category,
                mentions_count=item.mentions_count,
                severity_level=SeverityLevelEnum(item.severity_level),
                status=PainStatusEnum(item.status),
                confidence=1.0,
                first_detected_at=snapshot.generated_at,
                last_detected_at=snapshot.generated_at,
            )
            self._db.add(pain)
            await self._db.flush()

            self._db.add(SnapshotPain(snapshot_id=snapshot.id, pain_id=pain.id))

            for evidence_url in item.evidence_posts:
                self._db.add(
                    PainEvidence(
                        pain_id=pain.id,
                        source_type="post_url",
                        url=evidence_url,
                    )
                )

            if item.strategy and item.strategy.actions:
                self._db.add(
                    PainStrategy(
                        pain_id=pain.id,
                        description=strategy_to_description(item.strategy),
                        generated_by_llm=False,
                        approved_by_user=False,
                    )
                )

        add_action_log(
            self._db,
            user_id=user.id,
            action="analytics_snapshot_imported",
            entity_type="analysis_snapshot",
            entity_id=snapshot.id,
            details={
                "source_name": normalized.source_name,
                "source_format": normalized.source_format,
                "pains_count": len(normalized.pains),
            },
        )
        await self._db.commit()
        await self._db.refresh(snapshot)
        return snapshot
