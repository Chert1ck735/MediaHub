import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.comments import Comment
    from backend.db.pains import Pain


class CommentPain(Base, TimestampMixin):
    __tablename__ = "comment_pains"

    __table_args__ = (
        UniqueConstraint(
            "comment_id",
            "pain_id",
            name="uq_comment_pain",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=False, index=True
    )

    pain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pains.id", ondelete="CASCADE"), nullable=False, index=True
    )

    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comment: Mapped["Comment"] = relationship("Comment", back_populates="pain_links")
    pain: Mapped["Pain"] = relationship("Pain", back_populates="comment_links")
