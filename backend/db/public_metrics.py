import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin
from backend.db.enums import MetricPeriodEnum

if TYPE_CHECKING:
    from backend.db.public_social_links import PublicSocialLink


class PublicMetric(Base, TimestampMixin):
    __tablename__ = "public_metrics"
    __table_args__ = (
        UniqueConstraint(
            "public_social_link_id",
            "period",
            "metric_date",
            name="uq_public_metrics_link_period_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    public_social_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("public_social_links.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    period: Mapped[MetricPeriodEnum] = mapped_column(
        Enum(MetricPeriodEnum, name="metric_period_enum", create_type=False),
        nullable=False,
        default=MetricPeriodEnum.day,
    )

    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    subscribers_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_posts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_views: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_likes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_reposts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_views: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    avg_engagement: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    organic_reach: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    posting_regularity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    public_social_link: Mapped["PublicSocialLink"] = relationship(
        "PublicSocialLink"
    )
