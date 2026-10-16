import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.snapshot_pains import SnapshotPain


class AnalysisSnapshot(Base, TimestampMixin):
    __tablename__ = "analysis_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    public_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("publics.id", ondelete="SET NULL"), nullable=True
    )

    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )

    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="manual_import")
    source_format: Mapped[str] = mapped_column(String(64), nullable=False, default="pain_analytics_v1")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )

    global_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    citizens_requests: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    dissatisfaction_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    satisfaction_points: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_zones: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    quick_wins_30_days: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    strategic_actions_3_6_months: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    organization: Mapped["Organization"] = relationship("Organization")

    pain_links: Mapped[list["SnapshotPain"]] = relationship(
        "SnapshotPain",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )
