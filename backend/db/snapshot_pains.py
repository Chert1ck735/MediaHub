import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.analysis_snapshots import AnalysisSnapshot
    from backend.db.pains import Pain


class SnapshotPain(Base, TimestampMixin):
    __tablename__ = "snapshot_pains"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "pain_id", name="uq_snapshot_pains_snapshot_pain"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_snapshots.id", ondelete="CASCADE"), nullable=False, index=True
    )
    pain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pains.id", ondelete="CASCADE"), nullable=False, index=True
    )

    snapshot: Mapped["AnalysisSnapshot"] = relationship(
        "AnalysisSnapshot", back_populates="pain_links"
    )
    pain: Mapped["Pain"] = relationship("Pain")
