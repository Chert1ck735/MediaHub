import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import TimestampMixin
from backend.db.base import Base

if TYPE_CHECKING:
    from backend.db.pain_strategies import PainStrategy
    from backend.db.posts import Post


class StrategyPost(Base, TimestampMixin):
    __tablename__ = "strategy_posts"
    __table_args__ = (
        UniqueConstraint("strategy_id", "post_id", name="uq_strategy_posts_strategy_post"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    strategy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pain_strategies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    strategy: Mapped["PainStrategy"] = relationship("PainStrategy", back_populates="strategy_posts")
    post: Mapped["Post"] = relationship("Post", back_populates="strategy_links")
