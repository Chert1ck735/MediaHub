import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import TimestampMixin
from backend.db.base import Base
from backend.db.enums import ContentTypeEnum

if TYPE_CHECKING:
    from backend.db.posts import Post


class MediaItem(Base, TimestampMixin):
    """Медиа-вложение, привязанное к Post (таблица 'media' по media.sql)."""

    __tablename__ = "media"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)

    type: Mapped[ContentTypeEnum] = mapped_column(
        Enum(ContentTypeEnum, name="content_type_enum"),
        nullable=False,
        default=ContentTypeEnum.photo,
    )

    mime_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    post: Mapped["Post"] = relationship("Post", back_populates="media_items")
