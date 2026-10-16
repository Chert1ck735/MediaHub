import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.publics import Public
    from backend.db.social_networks import SocialNetwork
    from backend.db.publications import Publication


class PublicSocialLink(Base, TimestampMixin):
    """
    Ссылка на конкретное сообщество или страницу паблика
    в социальной сети.

    Связывает логическую сущность Public с её представлением
    в конкретной социальной сети.
    """

    __tablename__ = "public_social_links"
    __table_args__ = (
        UniqueConstraint(
            "public_id",
            "social_network_id",
            "external_public_id",
            name="uq_public_social_links_public_network_external",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publics.id", ondelete="CASCADE"), nullable=False, index=True
    )

    social_network_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("social_networks.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    external_public_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Автопарсер включён для этой ссылки. Отдельный флаг (не is_active): ссылку
    # можно держать активной для публикаций, но не гонять по ней ежедневный
    # ingest комментариев.
    autoparse_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    # Когда автопарсер в последний раз ПРОВЕРЯЛ эту ссылку на новые комменты
    # (не обязательно парсил — проверка могла не найти дифф). NULL = ни разу.
    # По этому полю воркер решает, наступил ли следующий период (см.
    # AUTOPARSE_INTERVAL_HOURS).
    last_autoparse_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Текст последней ошибки автопарсера по этой ссылке (или причина пропуска).
    # NULL = последний проход прошёл без ошибок. Показываем в «состоянии данных
    # по площадкам», чтобы админ видел, почему у ссылки не тянутся комментарии.
    last_autoparse_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    public: Mapped["Public"] = relationship("Public", back_populates="social_links")
    social_network: Mapped["SocialNetwork"] = relationship("SocialNetwork")
    publications: Mapped[list["Publication"]] = relationship(
        "Publication",
        back_populates="public_social_link",
        cascade="all, delete-orphan",
    )
