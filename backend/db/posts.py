import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Text, DateTime, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import (
    ContentTypeEnum,
    PostOriginEnum,
    PublicationStatusEnum,
)

if TYPE_CHECKING:
    from backend.db.events import Event
    from backend.db.publications import Publication
    from backend.db.media_items import MediaItem
    from backend.db.strategy_posts import StrategyPost
    from backend.db.users import User
    from backend.db.organizations import Organization
    from backend.db.tags import Tag
    from backend.db.publics import Public


class Post(Base, TimestampMixin):
    """
        Внутренний контент системы, предназначенный для публикации
        на одной или нескольких площадках.

    Хранит полный жизненный цикл контента:
        - черновик текста;
        - сгенерированный ИИ вариант;
        - финальную версию;
        - метаданные публикации;
        - автора, теги и связанные события.

    """

    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    text_draft: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_generated: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_final: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    origin: Mapped[Optional[PostOriginEnum]] = mapped_column(
        Enum(PostOriginEnum, name="post_origin_enum", create_type=False),
        nullable=False,
        default=PostOriginEnum.manual,
    )

    content_type: Mapped[Optional[ContentTypeEnum]] = mapped_column(
        Enum(ContentTypeEnum, name="content_type_enum", create_type=False),
        nullable=False,
        default=ContentTypeEnum.text,
    )
    status: Mapped[PublicationStatusEnum] = mapped_column(
        Enum(PublicationStatusEnum, name="publication_status_enum", create_type=False),
        nullable=False,
        default=PublicationStatusEnum.pending,
    )

    public_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("publics.id", ondelete="SET NULL"), nullable=True, index=True
    )

    event_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("events.id", ondelete="SET NULL"), nullable=True
    )

    source_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL"), nullable=True
    )

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    author_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )


    author: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="posts"
    )

    organization: Mapped["Organization"] = relationship(
        "Organization",
        back_populates="posts"
    )
    tags: Mapped[list["Tag"]] = relationship(
        "Tag",
        secondary="post_tags",
        back_populates="posts"
    )
    public: Mapped[Optional["Public"]] = relationship("Public")
    event: Mapped[Optional["Event"]] = relationship("Event")

    publications: Mapped[list["Publication"]] = relationship(
        "Publication",
        back_populates="post",
        cascade="all, delete-orphan",
    )

    media_items: Mapped[list["MediaItem"]] = relationship(
        "MediaItem",
        cascade="all, delete-orphan",
    )

    strategy_links: Mapped[list["StrategyPost"]] = relationship(
        "StrategyPost",
        back_populates="post",
        cascade="all, delete-orphan",
    )
