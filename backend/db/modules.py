import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Text, UUID, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped, relationship

from backend.db import TimestampMixin, Base

if TYPE_CHECKING:
    from backend.db.publics import Public


class Module(Base, TimestampMixin):
    __tablename__ = "modules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(
            "publics.id",
            ondelete="CASCADE"
        ),
        unique=True,
        nullable=False
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    goal: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    configuration: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict
    )

    public: Mapped["Public"] = relationship(
        "Public",
        back_populates="module"
    )
