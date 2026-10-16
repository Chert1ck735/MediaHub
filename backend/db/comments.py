import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.publications import Publication
    from backend.db.comment_analysis import CommentAnalysis
    from backend.db.comment_pains import CommentPain


class Comment(Base, TimestampMixin):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), nullable=False, index=True
    )

    parent_comment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), nullable=True, index=True
    )

    external_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )

    text: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    comment_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    publication: Mapped["Publication"] = relationship("Publication")

    analysis: Mapped[Optional["CommentAnalysis"]] = relationship(
        "CommentAnalysis",
        back_populates="comment",
        cascade="all, delete-orphan",
        uselist=False,
    )

    pain_links: Mapped[list["CommentPain"]] = relationship(
        "CommentPain",
        back_populates="comment",
        cascade="all, delete-orphan",
    )
