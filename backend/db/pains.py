import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, DateTime, ForeignKey, Enum, Float, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import PainStatusEnum, SeverityLevelEnum

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.publics import Public
    from backend.db.regions import Region
    from backend.db.comment_pains import CommentPain
    from backend.db.pain_strategies import PainStrategy


class Pain(Base, TimestampMixin):
    __tablename__ = "pains"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    public_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("publics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    region_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("regions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    severity_level: Mapped[SeverityLevelEnum] = mapped_column(
        Enum(SeverityLevelEnum, name="severity_level_enum", create_type=False),
        nullable=False,
        default=SeverityLevelEnum.medium,
    )
    status: Mapped[PainStatusEnum] = mapped_column(
        Enum(PainStatusEnum, name="pain_status_enum", create_type=False),
        nullable=False,
        default=PainStatusEnum.active,
    )
    mentions_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    first_detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped["Organization"] = relationship("Organization")
    public: Mapped[Optional["Public"]] = relationship("Public")
    region: Mapped[Optional["Region"]] = relationship("Region")
    comment_links: Mapped[list["CommentPain"]] = relationship(
        "CommentPain",
        back_populates="pain",
        cascade="all, delete-orphan",
    )
    strategies: Mapped[list["PainStrategy"]] = relationship(
        "PainStrategy",
        back_populates="pain",
        cascade="all, delete-orphan",
    )
