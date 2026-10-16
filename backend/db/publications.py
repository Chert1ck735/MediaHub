import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import ContentTypeEnum, PublicationStatusEnum

if TYPE_CHECKING:
    from backend.db.posts import Post
    from backend.db.public_social_links import PublicSocialLink


class Publication(Base, TimestampMixin):
    """
    Связь между внутренним постом системы и его публикацией
    на конкретной площадке социальной сети.

    Хранит информацию о размещении поста в социальной сети:
    идентификатор внешнего поста, URL публикации, статус,
    тип контента, время публикации и синхронизации.
    """

    __tablename__ = "publications"

    __table_args__ = (
        UniqueConstraint(
            "post_id", "public_social_link_id", name="uq_publications_post_link"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    public_social_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_social_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    external_post_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[PublicationStatusEnum] = mapped_column(
        Enum(PublicationStatusEnum, name="publication_status_enum", create_type=False),
        nullable=False,
        default=PublicationStatusEnum.published,
    )

    content_type: Mapped[ContentTypeEnum] = mapped_column(
        Enum(ContentTypeEnum, name="content_type_enum", create_type=False),
        nullable=False,
        default=ContentTypeEnum.text,
    )

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    post: Mapped["Post"] = relationship("Post", back_populates="publications")
    public_social_link: Mapped["PublicSocialLink"] = relationship(
        "PublicSocialLink", back_populates="publications"
    )
