import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.pains import Pain
    from backend.db.strategy_posts import StrategyPost


class PainStrategy(Base, TimestampMixin):
    __tablename__ = "pain_strategies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    pain_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pains.id", ondelete="CASCADE"), nullable=False, index=True
    )

    description: Mapped[str] = mapped_column(Text, nullable=False)
    generated_by_llm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    pain: Mapped["Pain"] = relationship("Pain", back_populates="strategies")

    strategy_posts: Mapped[list["StrategyPost"]] = relationship(
        "StrategyPost",
        back_populates="strategy",
        cascade="all, delete-orphan",
    )
