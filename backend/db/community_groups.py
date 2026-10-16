"""Группы сообществ и их состав.

«Сообщество» — это существующая сущность ``Public`` (``publics``): по ТЗ дубль
не создаём, используем то, что уже есть и уже привязано к организации.

Группа сообществ позволяет выдать право сразу на набор сообществ: grant на
группу распространяется на все входящие в неё сообщества.

Принадлежность одной организации, как и в ``user_groups``, обеспечена схемой
через составные внешние ключи, а не сервисным слоем.
"""
import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.publics import Public


class CommunityGroup(Base, TimestampMixin):
    __tablename__ = "community_groups"

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_community_groups_org_name"),
        UniqueConstraint("organization_id", "id", name="uq_community_groups_org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    organization: Mapped["Organization"] = relationship("Organization")

    communities: Mapped[list["Public"]] = relationship(
        "Public",
        secondary="community_group_members",
        viewonly=True,
    )


class CommunityGroupMember(Base):
    """Состав группы сообществ. ``public_id`` — это сообщество (``publics.id``)."""

    __tablename__ = "community_group_members"

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "community_group_id"],
            ["community_groups.organization_id", "community_groups.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_community_group_members_group_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "public_id"],
            ["publics.organization_id", "publics.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_community_group_members_public_org",
        ),
    )

    community_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )

    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
