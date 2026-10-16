import uuid

from sqlalchemy import ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base, TimestampMixin
from backend.db.enums import SystemStateEnum


class SystemState(Base, TimestampMixin):
    __tablename__ = "system_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    current_state: Mapped[SystemStateEnum] = mapped_column(
        Enum(SystemStateEnum), nullable=False
    )
