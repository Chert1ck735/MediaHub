"""Группы пользователей и их состав.

Группа — способ выдать одинаковые права сразу нескольким пользователям:
grant'ы, выданные группе, складываются с личными grant'ами участника.

Принадлежность одной организации обеспечена СХЕМОЙ, а не сервисным слоем:
``user_group_members`` несёт свой ``organization_id`` и ссылается составными
внешними ключами на ``user_groups(organization_id, id)`` и
``users(organization_id, id)``. Поэтому положить пользователя одной организации
в группу другой физически нельзя — БД отвергнет строку.
"""
import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from backend.db.organizations import Organization
    from backend.db.users import User


class UserGroup(Base, TimestampMixin):
    __tablename__ = "user_groups"

    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_user_groups_org_name"),
        # Цель для составного FK из user_group_members (см. модуль-docstring).
        UniqueConstraint("organization_id", "id", name="uq_user_groups_org_id"),
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

    members: Mapped[list["User"]] = relationship(
        "User",
        secondary="user_group_members",
        back_populates="groups",
        viewonly=True,
    )


class UserGroupMember(Base):
    """Состав группы. PK по паре — дубли участника невозможны."""

    __tablename__ = "user_group_members"

    __table_args__ = (
        # Составные FK: организация участника обязана совпадать с организацией
        # группы. ON UPDATE CASCADE — чтобы перенос сущности между организациями
        # не оставлял висячую строку (а конфликтующий перенос честно падал).
        ForeignKeyConstraint(
            ["organization_id", "user_group_id"],
            ["user_groups.organization_id", "user_groups.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_user_group_members_group_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["users.organization_id", "users.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
            name="fk_user_group_members_user_org",
        ),
    )

    user_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        index=True,
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
