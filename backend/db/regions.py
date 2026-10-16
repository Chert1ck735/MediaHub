import uuid
from typing import Optional

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import TimestampMixin, Organization
from backend.db.base import Base


class Region(TimestampMixin, Base):
    __tablename__ = "regions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True)

    organizations: Mapped[list["Organization"]] = relationship(
        "Organization",
        back_populates="region",
    )
