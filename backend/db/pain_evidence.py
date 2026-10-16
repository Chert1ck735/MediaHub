import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.comments import Comment
    from backend.db.pains import Pain
    from backend.db.publications import Publication


class PainEvidence(Base, TimestampMixin):
    __tablename__ = "pain_evidence"
    __table_args__ = (
        UniqueConstraint("pain_id", "comment_id", name="uq_pain_evidence_pain_comment"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    pain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pains.id", ondelete="CASCADE"), nullable=False, index=True
    )
    publication_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL"), nullable=True
    )
    comment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="post_url")
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    pain: Mapped["Pain"] = relationship("Pain")
    publication: Mapped[Optional["Publication"]] = relationship("Publication")
    comment: Mapped[Optional["Comment"]] = relationship("Comment")
