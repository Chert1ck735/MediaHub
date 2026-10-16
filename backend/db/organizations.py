import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import String, Text, Enum, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db import TimestampMixin, Base, OrgType

if TYPE_CHECKING:
    from backend.db.regions import Region
    from backend.db.users import User
    from backend.db.posts import Post
    from backend.db.events import Event
    from backend.db.publics import Public


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    type: Mapped[OrgType] = mapped_column(
        Enum(
            OrgType,
            name="org_type_enum",
            create_type=False
        ),
        nullable=False
    )

    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True
    )

    region_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("regions.id"),
        nullable=True
    )

    municipality_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    region: Mapped[Optional["Region"]] = relationship(
        "Region",
        back_populates="organizations"
    )

    users: Mapped[list["User"]] = relationship(
        "User",
        back_populates="organization",
        cascade="all, delete-orphan"
    )

    publics: Mapped[list["Public"]] = relationship(
        "Public",
        back_populates="organization",
        cascade="all, delete-orphan"
    )

    posts: Mapped[list["Post"]] = relationship(
        "Post",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True
    )

    events: Mapped[list["Event"]] = relationship(
        "Event",
        back_populates="organization",
        cascade="all, delete-orphan",
        passive_deletes=True
    )
